"""
app/routes/audit.py
rotas do log de auditoria: /admin/audit-log, /api/admin/*/sessions
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import (
    AUDIT_LOG_INFLUX_LIMIT,
    INFLUX_BUCKET,
    INFLUX_ORG,
    LIMITE_DIAS_HISTORICO,
    SESSIONS_LOG_LIMIT,
)
from app.dependencies import _verificar_acesso_tenant, obter_payload_token, require_superadmin
from app.services.database import validar_tenant_id
from app.services.influx_client import get_influx_client

logger = logging.getLogger("metric4.api")

router = APIRouter()


def _parse_query_ts(val: str) -> datetime:
    normalizado = val.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalizado)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _flux_time_literal(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolver_intervalo_audit(ts_inicio: Optional[str], ts_fim: Optional[str]) -> tuple[str, str]:
    if not ts_inicio and not ts_fim:
        return "-100y", "now()"
    if ts_inicio and ts_fim:
        return _flux_time_literal(_parse_query_ts(ts_inicio)), _flux_time_literal(_parse_query_ts(ts_fim))
    if ts_inicio:
        return _flux_time_literal(_parse_query_ts(ts_inicio)), "now()"
    fim = _parse_query_ts(ts_fim)  # type: ignore[arg-type]
    inicio = fim - timedelta(days=LIMITE_DIAS_HISTORICO)
    return _flux_time_literal(inicio), _flux_time_literal(fim)


def _match_parcial_ci(valor: Optional[str], filtro: Optional[str]) -> bool:
    if not filtro:
        return True
    return filtro.lower() in (valor or "").lower()


def _carregar_system_access_log(start: str, stop: str, tenant_id: Optional[str] = None) -> list[dict]:
    if not INFLUX_BUCKET or not INFLUX_ORG:
        return []

    tenant_filter = ""
    if tenant_id and validar_tenant_id(tenant_id):
        tenant_filter = f'|> filter(fn: (r) => r["tenant_id"] == "{tenant_id}")'

    query = f"""
        from(bucket: "{INFLUX_BUCKET}")
        |> range(start: {start}, stop: {stop})
        |> filter(fn: (r) => r["_measurement"] == "system_access_log")
        {tenant_filter}
        |> filter(fn: (r) => r["_field"] == "action" or r["_field"] == "details")
        |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
        |> group()
        |> sort(columns:["_time"], desc:true)
        |> limit(n: {AUDIT_LOG_INFLUX_LIMIT})
    """
    resultados = get_influx_client().query_api().query(org=INFLUX_ORG, query=query)
    eventos: list[dict] = []
    for tabela in resultados:
        for registro in tabela.records:
            ts = registro.values.get("_time")
            eventos.append({
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "tenant_id": registro.values.get("tenant_id") or "",
                "username":  registro.values.get("user_id") or "",
                "acao":      registro.values.get("action") or "",
                "detalhes":  registro.values.get("details") or "",
            })
    return eventos


@router.get("/admin/audit-log", tags=["Admin"])
def admin_audit_log(
    tenant_id: Optional[str] = Query(None),
    username: Optional[str] = Query(None),
    acao: Optional[str] = Query(None),
    detalhes: Optional[str] = Query(None),
    ts_inicio: Optional[str] = Query(None),
    ts_fim: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=2000),
    _: dict = Depends(require_superadmin),
):
    page_size = min(max(page_size, 1), 2000)
    try:
        if tenant_id and not validar_tenant_id(tenant_id):
            return {"total": 0, "page": page, "page_size": page_size, "resultados": []}

        try:
            start, stop = _resolver_intervalo_audit(ts_inicio, ts_fim)
        except (ValueError, TypeError):
            return {"total": 0, "page": page, "page_size": page_size, "resultados": []}

        eventos = _carregar_system_access_log(start, stop, tenant_id)

        filtrados = [
            e for e in eventos
            if _match_parcial_ci(e.get("username"), username)
            and _match_parcial_ci(e.get("acao"), acao)
            and _match_parcial_ci(e.get("detalhes"), detalhes)
            and (not tenant_id or e.get("tenant_id") == tenant_id)
        ]

        total = len(filtrados)
        offset = (page - 1) * page_size
        pagina = filtrados[offset: offset + page_size]

        return {"total": total, "page": page, "page_size": page_size, "resultados": pagina}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha ao consultar audit-log: %s", exc)
        return {"total": 0, "page": page, "page_size": page_size, "resultados": []}


@router.get("/api/admin/tenants/{tenant_id}/sessions", tags=["Admin"])
def admin_get_tenant_sessions(
    tenant_id: str,
    start: str = Query("-30d"),
    stop: str = Query("now()"),
    action: Optional[str] = Query(None),
    payload: dict = Depends(obter_payload_token),
):
    _verificar_acesso_tenant(tenant_id, payload)
    action_filter = f'|> filter(fn: (r) => r["action"] == "{action}")' if action else ""
    query = f"""
        from(bucket: "{INFLUX_BUCKET}")
        |> range(start: {start}, stop: {stop})
        |> filter(fn: (r) => r["_measurement"] == "system_access_log")
        |> filter(fn: (r) => r["tenant_id"] == "{tenant_id}")
        |> filter(fn: (r) => r["_field"] == "action" or r["_field"] == "details")
        |> pivot(rowKey:["_time"], columnKey:["_field"], valueColumn:"_value")
        {action_filter}
        |> group()
        |> sort(columns:["_time"], desc:true)
        |> limit(n: {SESSIONS_LOG_LIMIT})
    """
    try:
        resultados = get_influx_client().query_api().query(org=INFLUX_ORG, query=query)
        eventos = []
        for tabela in resultados:
            for registro in tabela.records:
                ts = registro.values.get("_time")
                eventos.append({
                    "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                    "user_id":   registro.values.get("user_id"),
                    "tenant_id": registro.values.get("tenant_id"),
                    "action":    registro.values.get("action"),
                    "details":   registro.values.get("details") or "",
                })
        return {"events": eventos}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao buscar logs: {exc}")
