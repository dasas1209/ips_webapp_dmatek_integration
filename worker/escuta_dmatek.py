"""
worker/escuta_dmatek.py
motor de escuta websocket dmatek para influxdb
"""

import asyncio
import json
import logging
import time

import websockets
from influxdb_client import Point  # type: ignore
from influxdb_client.client.write_api import SYNCHRONOUS  # type: ignore

from config import (
    ENDPOINT_DMATEK,
    INFLUX_BUCKET,
    INFLUX_ORG,
    IP_SERVIDOR_DMATEK,
    LIMITE_X_CM,
    LIMITE_Y_CM,
    MATRIZ_RELOAD_INTERVAL_SEG,
    PORTA_DMATEK,
    TIMEOUT_MOVIMENTO,
    TIMEOUT_REPOUSO,
)
from app.services.database import carregar_matriz_clientes
from app.services.influx_client import get_influx_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("metric4.worker")

_write_api = get_influx_client().write_api(write_options=SYNCHRONOUS)

# estado em memoria: tag_id -> {timestamp, em_repouso, status}
registo_de_tags: dict[str, dict] = {}

# mapeamento tag_id -> tenant_id recarregado periodicamente
MATRIZ_CLIENTES: dict[str, str] = carregar_matriz_clientes()


async def _escrever_influx(ponto: Point) -> None:
    await asyncio.to_thread(
        _write_api.write,
        bucket=INFLUX_BUCKET,
        org=INFLUX_ORG,
        record=ponto,
    )


async def escrever_evento_auditoria(
    tag_id: str,
    tipo: str,
    descricao: str,
    *,
    coord_x: float | None = None,
    coord_y: float | None = None,
) -> None:
    """grava evento de auditoria (offline, recovery, emergencia) no bucket influx"""
    tenant_id = MATRIZ_CLIENTES.get(tag_id, "cliente_desconhecido")
    ponto = (
        Point("evento_auditoria")
        .tag("tag_id", tag_id)
        .tag("tenant_id", tenant_id)
        .tag("tipo", tipo)
        .field("descricao", (descricao or "")[:1024] or "-")
    )
    if coord_x is not None:
        ponto = ponto.field("coord_x", float(coord_x))
    if coord_y is not None:
        ponto = ponto.field("coord_y", float(coord_y))
    await _escrever_influx(ponto)


async def monitorizar_saude() -> None:
    """tarefa paralela que detecta tags offline"""
    while True:
        agora = time.time()
        for tag_id, info in registo_de_tags.items():
            tempo_sem_sinal = agora - info["timestamp"]
            limite = TIMEOUT_REPOUSO if info["em_repouso"] else TIMEOUT_MOVIMENTO

            if tempo_sem_sinal > limite and info["status"] == "online":
                info["status"] = "offline"
                msg = f"Sem sinal ha {tempo_sem_sinal:.1f}s"
                logger.warning("tag %s ficou offline (%s)", tag_id, msg)
                await escrever_evento_auditoria(tag_id, "OFFLINE_ALARM", msg)

        await asyncio.sleep(2)


async def recarregar_matriz_periodicamente() -> None:
    """recarrega mapeamento tag->tenant sem reiniciar o processo"""
    global MATRIZ_CLIENTES
    while True:
        await asyncio.sleep(MATRIZ_RELOAD_INTERVAL_SEG)
        nova = carregar_matriz_clientes()
        if nova:
            MATRIZ_CLIENTES = nova
            logger.info("matriz recarregada: %d tag(s)", len(MATRIZ_CLIENTES))


def _processar_tag(tag: dict, agora: float) -> Point | None:
    """valida e constroi o ponto influx para uma tag; devolve None se fora do mapa"""
    tag_id = tag.get("TagID", "Desconhecida")
    px = tag.get("PX", -1)
    py = tag.get("PY", -1)
    nm_time = tag.get("NMTime", 0)
    estado_tag = tag.get("MType", "Normal")
    nivel_bateria = int(tag.get("Batt", 0))

    if not (0 <= px <= LIMITE_X_CM and 0 <= py <= LIMITE_Y_CM):
        logger.warning("tag %s fora do mapa (x:%s y:%s) — ignorada", tag_id, px, py)
        return None

    return tag_id, px, py, nm_time, estado_tag, nivel_bateria


async def _registar_recuperacao(tag_id: str, px: float, py: float) -> None:
    logger.info("tag %s voltou online", tag_id)
    await escrever_evento_auditoria(
        tag_id,
        "ONLINE_RECOVERY",
        "A tag voltou a comunicar com a rede.",
        coord_x=float(px),
        coord_y=float(py),
    )


async def _registar_emergencia(tag_id: str, px: float, py: float) -> None:
    logger.warning("botao de panico na tag %s (x:%s y:%s)", tag_id, px, py)
    await escrever_evento_auditoria(
        tag_id,
        "EMERGENCY_BUTTON",
        f"Botao de panico premido na coordenada X:{px} Y:{py}",
        coord_x=float(px),
        coord_y=float(py),
    )


async def _processar_pacote(dados_brutos: str, agora: float) -> None:
    pacote = json.loads(dados_brutos)
    lista_de_tags = pacote if isinstance(pacote, list) else [pacote]

    for tag in lista_de_tags:
        resultado = _processar_tag(tag, agora)
        if resultado is None:
            continue

        tag_id, px, py, nm_time, estado_tag, nivel_bateria = resultado

        if estado_tag == "Urgency":
            await _registar_emergencia(tag_id, px, py)

        estava_offline = registo_de_tags.get(tag_id, {}).get("status") == "offline"
        registo_de_tags[tag_id] = {
            "timestamp": agora,
            "em_repouso": nm_time > 0,
            "status": "online",
        }

        if estava_offline:
            await _registar_recuperacao(tag_id, px, py)

        id_do_cliente = MATRIZ_CLIENTES.get(tag_id, "cliente_desconhecido")
        modo = "REPOUSO" if nm_time > 0 else "MOVIMENTO"

        ponto = (
            Point("posicao_tag")
            .tag("tag_id", tag_id)
            .tag("tenant_id", id_do_cliente)
            .field("coord_x", px)
            .field("coord_y", py)
            .field("nm_time", nm_time)
            .field("status", estado_tag)
            .field("bateria", nivel_bateria)
        )

        await _escrever_influx(ponto)
        logger.info("[%s] tag %s | %s | x:%s y:%s", id_do_cliente, tag_id, modo, px, py)


async def escutar_fabrica() -> None:
    """ouve o websocket dmatek e grava coordenadas no influxdb"""
    uri = f"ws://{IP_SERVIDOR_DMATEK}:{PORTA_DMATEK}{ENDPOINT_DMATEK}"
    logger.info("valvula de dados aberta em: %s", uri)

    try:
        async with websockets.connect(uri) as websocket:
            while True:
                dados_brutos = await websocket.recv()
                agora = time.time()
                try:
                    await _processar_pacote(dados_brutos, agora)
                except Exception:
                    logger.exception("falha ao processar pacote")
    except Exception:
        logger.exception("ligacao websocket perdida")


async def main() -> None:
    await asyncio.gather(
        escutar_fabrica(),
        monitorizar_saude(),
        recarregar_matriz_periodicamente(),
    )


if __name__ == "__main__":
    asyncio.run(main())
