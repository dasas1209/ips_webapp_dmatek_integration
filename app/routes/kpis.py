"""
app/routes/kpis.py
rotas de kpis: /kpis, /relatorio/dados
"""

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from config import INFLUX_BUCKET, INFLUX_ORG, JANELA_KPI_HORAS, LIMITE_DIAS_HISTORICO
from app.dependencies import aplicar_rate_limit, log_audit_event, obter_payload_token
from app.services.database import get_db_connection, obter_limites_mapa
from app.services.influx_client import get_influx_client
from app.services.kpi_engine import RegistoTag, calcular_kpis

logger = logging.getLogger("metric4.api")

router = APIRouter()


def _registos_de_tabelas_influx(resultado) -> list[RegistoTag]:
    registos: list[RegistoTag] = []
    for table in resultado:
        for record in table.records:
            tag_id = record.values.get("tag_id")
            x      = record.values.get("coord_x")
            y      = record.values.get("coord_y")
            if tag_id is None or x is None or y is None:
                continue
            registos.append(RegistoTag(
                tag_id=tag_id,
                x=x,
                y=y,
                timestamp=record.values.get("_time"),
                bateria=record.values.get("bateria"),
            ))
    return registos


async def _obter_kpis_turno_por_tenant(tenant_id: str):
    query = f"""
        from(bucket: "{INFLUX_BUCKET}")
        |> range(start: -{JANELA_KPI_HORAS}h)
        |> filter(fn: (r) => r["_measurement"] == "posicao_tag")
        |> filter(fn: (r) => r["tenant_id"] == "{tenant_id}")
        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        |> group(columns: ["tag_id"])
        |> sort(columns: ["_time"])
    """
    try:
        resultado = get_influx_client().query_api().query(org=INFLUX_ORG, query=query)
        registos = _registos_de_tabelas_influx(resultado)
        tags = calcular_kpis(registos)

        distancia_m     = round(sum(t.distancia_m for t in tags.values()), 2)
        total_leituras  = sum(t.leituras_totais for t in tags.values())
        total_movimento = sum(t.leituras_em_movimento for t in tags.values())
        taxa_utilizacao = round((total_movimento / total_leituras) * 100, 1) if total_leituras > 0 else 0.0

        baterias = [t.bateria_ultima for t in tags.values() if t.bateria_ultima > 0]
        bateria_media = round(sum(baterias) / len(baterias), 1) if baterias else 0.0

        try:
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM tags WHERE cliente_id = ?", (tenant_id,)
                ).fetchone()
            total_assets_bd = row["n"] if row else 0
        except Exception:
            total_assets_bd = len(tags)

        return {
            "sucesso":   True,
            "tenant_id": tenant_id,
            "kpis": {
                "distancia_percorrida_metros": distancia_m,
                "taxa_utilizacao_perc":        taxa_utilizacao,
                "bateria_media_frota_perc":    bateria_media,
                "tags_ativas_turno":           len(tags),
                "total_assets":                total_assets_bd,
            },
            "grafico_distancias": {t: kpi.distancia_m for t, kpi in tags.items()},
            "grafico_utilizacao": {t: kpi.taxa_utilizacao_perc for t, kpi in tags.items()},
            "grafico_bateria":    {t: round(kpi.bateria_ultima, 1) for t, kpi in tags.items()},
        }
    except Exception as exc:
        return {"sucesso": False, "erro": str(exc)}


@router.get("/kpis", tags=["KPIs"])
async def obter_kpis_turno(tenant_id: str = Depends(aplicar_rate_limit)):
    logger.info("Consulta de KPIs para tenant_id=%s", tenant_id)
    return await _obter_kpis_turno_por_tenant(tenant_id)


@router.get("/kpis/{tenant_id}", tags=["KPIs"], include_in_schema=False)
async def obter_kpis_turno_legado(
    tenant_id: str,
    token_tenant: str = Depends(aplicar_rate_limit),
):
    if tenant_id != token_tenant:
        raise HTTPException(status_code=403, detail="Acesso negado: nao tem permissao para ver os KPIs deste cliente.")
    logger.info("Consulta de KPIs (legacy) para tenant_id=%s", token_tenant)
    return await _obter_kpis_turno_por_tenant(token_tenant)


def _eventos_auditoria_influx_para_incidentes(tabelas, limite_x: float, limite_y: float) -> list[dict]:
    eventos: list[dict] = []
    for table in tabelas:
        for record in table.records:
            tag_id = record.values.get("tag_id")
            tipo   = record.values.get("tipo")
            ts     = record.values.get("_time")
            if tag_id is None or tipo is None or ts is None:
                continue

            descricao = record.values.get("descricao") or ""
            if isinstance(descricao, str) and descricao == "-":
                descricao = ""

            x_norm, y_norm = None, None
            x_cm = record.values.get("coord_x")
            y_cm = record.values.get("coord_y")
            if x_cm is not None and y_cm is not None:
                try:
                    x_norm = round(float(x_cm) / limite_x, 5)
                    y_norm = round(float(y_cm) / limite_y, 5)
                except (TypeError, ValueError):
                    pass
            if x_norm is None and descricao:
                match = re.search(r"X:(\d+(?:\.\d+)?)\s+Y:(\d+(?:\.\d+)?)", str(descricao))
                if match:
                    try:
                        x_norm = round(float(match.group(1)) / limite_x, 5)
                        y_norm = round(float(match.group(2)) / limite_y, 5)
                    except (TypeError, ValueError):
                        pass

            ts_iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            eventos.append({
                "tag_id":    tag_id,
                "timestamp": ts_iso,
                "tipo":      tipo,
                "descricao": descricao,
                "x":         x_norm,
                "y":         y_norm,
                "fonte":     "influx_evento",
            })
    return eventos


@router.get("/relatorio/dados", tags=["Auditoria"])
def obter_dados_auditoria(
    inicio: str = Query(..., description="Inicio ISO 8601, ex: 2026-05-11T06:00:00Z"),
    fim:    str = Query(..., description="Fim ISO 8601, ex: 2026-05-11T14:00:00Z"),
    background_tasks: BackgroundTasks = None,
    payload: dict = Depends(obter_payload_token),
    tenant_id: str = Depends(aplicar_rate_limit),
):
    """consulta fluxo temporal completo para dashboard de auditoria"""
    try:
        dt_inicio = datetime.fromisoformat(inicio.replace("Z", "+00:00"))
        dt_fim    = datetime.fromisoformat(fim.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="Formato de data invalido. Use ISO 8601.")

    if dt_fim <= dt_inicio:
        raise HTTPException(status_code=422, detail="fim deve ser posterior a inicio.")
    if (dt_fim - dt_inicio).days > LIMITE_DIAS_HISTORICO:
        raise HTTPException(status_code=422, detail=f"Intervalo maximo permitido: {LIMITE_DIAS_HISTORICO} dias.")

    agora_utc = datetime.now(timezone.utc)
    if dt_inicio < agora_utc - timedelta(days=LIMITE_DIAS_HISTORICO):
        raise HTTPException(status_code=422, detail=f"inicio nao pode ser anterior a {LIMITE_DIAS_HISTORICO} dias atras.")

    inicio_safe = dt_inicio.isoformat()
    fim_safe    = dt_fim.isoformat()

    query_trajetoria = f"""
        from(bucket: "{INFLUX_BUCKET}")
        |> range(start: {inicio_safe}, stop: {fim_safe})
        |> filter(fn: (r) => r["_measurement"] == "posicao_tag")
        |> filter(fn: (r) => r["tenant_id"] == "{tenant_id}")
        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        |> group(columns: ["tag_id"])
        |> sort(columns: ["_time"])
    """
    query_eventos_auditoria = f"""
        from(bucket: "{INFLUX_BUCKET}")
        |> range(start: {inicio_safe}, stop: {fim_safe})
        |> filter(fn: (r) => r["_measurement"] == "evento_auditoria")
        |> filter(fn: (r) => r["tenant_id"] == "{tenant_id}")
        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        |> sort(columns: ["_time"])
    """

    try:
        limite_x, limite_y = obter_limites_mapa(tenant_id)
        qa = get_influx_client().query_api()
        resultado         = qa.query(org=INFLUX_ORG, query=query_trajetoria)
        resultado_eventos = qa.query(org=INFLUX_ORG, query=query_eventos_auditoria)

        esparguete_pontos: list[dict] = []
        registos: list[RegistoTag] = []

        for table in resultado:
            for record in table.records:
                tag_id  = record.values.get("tag_id")
                x_cm    = record.values.get("coord_x")
                y_cm    = record.values.get("coord_y")
                bateria = record.values.get("bateria")
                ts      = record.values.get("_time")

                if tag_id is None or x_cm is None or y_cm is None:
                    continue

                x_norm = round(x_cm / limite_x, 5)
                y_norm = round(y_cm / limite_y, 5)
                ts_iso = ts.isoformat() if ts else None

                esparguete_pontos.append({"tag_id": tag_id, "x": x_norm, "y": y_norm, "t": ts_iso})
                registos.append(RegistoTag(tag_id=tag_id, x=x_cm, y=y_cm, timestamp=ts, bateria=bateria))

        tags = calcular_kpis(registos)

        incidentes: list[dict] = []
        try:
            incidentes = _eventos_auditoria_influx_para_incidentes(resultado_eventos, limite_x, limite_y)
        except Exception:
            logger.exception("falha ao agregar eventos evento_auditoria do influx")

        incidentes.sort(key=lambda x: x.get("timestamp", ""))
        alertas_por_tag = Counter(inc["tag_id"] for inc in incidentes)

        distancia_frota_m   = 0.0
        baterias_para_media: list[float] = []
        kpis_por_tag = []

        for tag_id, kpi in tags.items():
            distancia_frota_m += kpi.distancia_m
            if kpi.bateria_ultima > 0:
                baterias_para_media.append(kpi.bateria_ultima)
            kpis_por_tag.append({
                "tag_id":           tag_id,
                "distancia_m":      kpi.distancia_m,
                "oee_perc":         kpi.taxa_utilizacao_perc,
                "bateria_min_perc": kpi.bateria_min_perc,
                "tempo_ocioso_min": round(kpi.tempo_ocioso_seg / 60, 1),
                "num_alertas":      alertas_por_tag[tag_id],
            })

        kpis_por_tag.sort(key=lambda t: t["tag_id"])
        bateria_media_frota = round(sum(baterias_para_media) / len(baterias_para_media), 1) if baterias_para_media else 0.0

        username = payload.get("sub", "desconhecido")
        if background_tasks:
            background_tasks.add_task(
                log_audit_event, username, tenant_id, "audit_report_viewed",
                f"Periodo: {inicio} -> {fim} | Tags ativas: {len(tags)} | Incidentes: {len(incidentes)}.",
            )

        return {
            "sucesso":  True,
            "tenant_id": tenant_id,
            "periodo":  {"inicio": inicio, "fim": fim},
            "kpis_frota": {
                "distancia_total_m":  round(distancia_frota_m, 2),
                "bateria_media_perc": bateria_media_frota,
                "total_incidentes":   len(incidentes),
                "tags_ativas":        len(tags),
            },
            "kpis_por_tag":      kpis_por_tag,
            "esparguete_pontos": esparguete_pontos,
            "incidentes":        incidentes,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar dados de auditoria: {exc}")
