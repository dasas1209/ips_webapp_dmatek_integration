"""
escuta_dmatek.py
motor de escuta websocket dmatek para influxdb
"""

import asyncio
import json
import time
import csv
from datetime import datetime

import websockets
from influxdb_client import InfluxDBClient, Point  # type: ignore
from influxdb_client.client.write_api import SYNCHRONOUS

from config import (
    INFLUX_URL,
    INFLUX_TOKEN,
    INFLUX_ORG,
    INFLUX_BUCKET,
    LIMITE_X_CM,
    LIMITE_Y_CM,
    TIMEOUT_MOVIMENTO,
    TIMEOUT_REPOUSO,
    IP_SERVIDOR_DMATEK,
    PORTA_DMATEK,
    ENDPOINT_DMATEK,
)
from shared import carregar_matriz_clientes

# configuracao do influxdb
_influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)  # type: ignore
_write_api     = _influx_client.write_api(write_options=SYNCHRONOUS)

# estado em memoria
registo_de_tags: dict[str, dict] = {}

# matriz de tags e clientes
MATRIZ_CLIENTES: dict[str, str] = carregar_matriz_clientes()


# log de eventos criticos

def registar_evento(tag_id: str, evento: str, detalhes: str) -> None:
    """regista linha de erro no ficheiro csv"""
    hora_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("auditoria_tags.csv", mode="a", newline="", encoding="utf-8") as fh:
        csv.writer(fh, delimiter=";").writerow([hora_atual, tag_id, evento, detalhes])


# rotinas de verificacao de saude

async def monitorizar_saude() -> None:
    """tarefa paralela que detecta tags offline"""
    while True:
        agora = time.time()
        for tag_id, info in registo_de_tags.items():
            tempo_sem_sinal = agora - info["timestamp"]
            limite = TIMEOUT_REPOUSO if info["em_repouso"] else TIMEOUT_MOVIMENTO

            if tempo_sem_sinal > limite and info["status"] == "online":
                info["status"] = "offline"
                msg = f"Sem sinal há {tempo_sem_sinal:.1f}s"
                print(f"[ALERTA] Tag {tag_id} ficou OFFLINE! ({msg})")
                registar_evento(tag_id, "OFFLINE_ALARM", msg)

        await asyncio.sleep(2)


# comunicacao principal

async def escrever_influx(ponto: Point) -> None:
    """delega a escrita síncrona do influx para thread paralela"""
    await asyncio.to_thread(
        _write_api.write,
        bucket=INFLUX_BUCKET,
        org=INFLUX_ORG,
        record=ponto,
    )


async def escutar_fabrica() -> None:
    """ouve o websocket dmatek e grava coordenadas no influxdb"""
    uri = f"ws://{IP_SERVIDOR_DMATEK}:{PORTA_DMATEK}{ENDPOINT_DMATEK}"
    print(f"[INFO] Válvula de dados aberta em: {uri}")

    try:
        async with websockets.connect(uri) as websocket:
            while True:
                dados_brutos = await websocket.recv()
                agora = time.time()

                try:
                    pacote = json.loads(dados_brutos)
                    lista_de_tags = pacote if isinstance(pacote, list) else [pacote]

                    for tag in lista_de_tags:
                        tag_id        = tag.get("TagID", "Desconhecida")
                        px            = tag.get("PX", -1)
                        py            = tag.get("PY", -1)
                        nm_time       = tag.get("NMTime", 0)
                        estado_tag    = tag.get("MType", "Normal")
                        nivel_bateria = int(tag.get("Batt", 0))

                        # ignora tags fora das dimensoes permitidas
                        if not (0 <= px <= LIMITE_X_CM and 0 <= py <= LIMITE_Y_CM):
                            print(f"[POKA-YOKE] Tag {tag_id} fora do mapa (X:{px} Y:{py}). Ignorada.")
                            continue

                        # alerta de emergência activado
                        if estado_tag == "Urgency":
                            print(f"[EMERGÊNCIA] Botão de pânico na Tag {tag_id}!")
                            registar_evento(
                                tag_id,
                                "EMERGENCY_BUTTON",
                                f"Botão de pânico premido na coordenada X:{px} Y:{py}",
                            )

                        # tag recuperada e novamente activa
                        estava_offline = registo_de_tags.get(tag_id, {}).get("status") == "offline"
                        registo_de_tags[tag_id] = {
                            "timestamp":  agora,
                            "em_repouso": nm_time > 0,
                            "status":     "online",
                        }
                        if estava_offline:
                            print(f"[RECOVERY] Tag {tag_id} voltou a estar ONLINE.")
                            registar_evento(tag_id, "ONLINE_RECOVERY", "A tag voltou a comunicar com a rede.")

                        modo = "REPOUSO" if nm_time > 0 else "MOVIMENTO"

                        # associa o registo ao tenant actual
                        id_do_cliente = MATRIZ_CLIENTES.get(tag_id, "cliente_desconhecido")

                        ponto = (
                            Point("posicao_tag")
                            .tag("tag_id",    tag_id)
                            .tag("tenant_id", id_do_cliente)
                            .field("coord_x",  px)
                            .field("coord_y",  py)
                            .field("nm_time",  nm_time)
                            .field("status",   estado_tag)
                            .field("bateria",  nivel_bateria)
                        )

                        # grava na base de dados
                        await escrever_influx(ponto)
                        print(f"[{id_do_cliente}] Tag {tag_id} | {modo} | X:{px} Y:{py}")

                except Exception as exc:
                    print(f"[ERRO] Falha ao processar pacote: {exc}")

    except Exception as exc:
        print(f"[ERRO] Ligação WebSocket perdida: {exc}")


# arranque da aplicacao

async def main() -> None:
    await asyncio.gather(escutar_fabrica(), monitorizar_saude())


if __name__ == "__main__":
    asyncio.run(main())
