"""
app/dependencies.py
dependencias partilhadas: jwt, rate limiting, roles, log de auditoria
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from influxdb_client import Point  # type: ignore
from jose import JWTError, jwt  # type: ignore

from config import (
    ALGORITHM,
    INFLUX_BUCKET,
    INFLUX_ORG,
    SECRET_KEY,
    TOKEN_EXPIRY_HOURS,
)
from app.services.database import validar_tenant_id
from app.services.influx_client import get_influx_client

logger = logging.getLogger("metric4.api")

# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------

class TenantRateLimiter:
    """throttling em memoria por chave para reduzir risco de noisy neighbor e brute force"""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._state: dict[str, dict[str, float | int]] = {}
        self._lock = Lock()

    def allow(self, chave: str) -> bool:
        now = time.monotonic()
        with self._lock:
            estado = self._state.get(chave)
            if estado is None or (now - float(estado["window_start"])) >= self.window_seconds:
                self._state[chave] = {"window_start": now, "count": 1}
                return True
            estado["count"] = int(estado["count"]) + 1
            return int(estado["count"]) <= self.max_requests


tenant_rate_limiter = TenantRateLimiter(max_requests=120, window_seconds=60)
login_rate_limiter = TenantRateLimiter(max_requests=10, window_seconds=60)

# ---------------------------------------------------------------------------
# jwt
# ---------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def criar_token_jwt(dados: dict) -> str:
    payload = dados.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)  # type: ignore


def obter_payload_token(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])  # type: ignore
        if not payload.get("tenant_id"):
            raise HTTPException(status_code=401, detail="Token sem identificacao de cliente.")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Acesso negado: token invalido ou expirado.")


def verificar_token(payload: dict = Depends(obter_payload_token)) -> str:
    return payload["tenant_id"]

# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------

def require_admin(payload: dict = Depends(obter_payload_token)) -> str:
    if payload.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Acesso negado: apenas o administrador do sistema.")
    return payload["tenant_id"]


def require_superadmin(payload: dict = Depends(obter_payload_token)) -> dict:
    if payload.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Acesso negado: apenas superadmin.")
    return payload


def _verificar_acesso_tenant(tenant_alvo: str, payload: dict) -> None:
    role = payload.get("role")
    if role == "superadmin":
        return
    if role == "admin" and payload.get("tenant_id") == tenant_alvo:
        return
    raise HTTPException(status_code=403, detail="Acesso negado: sem permissao para este tenant.")

# ---------------------------------------------------------------------------
# rate limit dependency
# ---------------------------------------------------------------------------

def aplicar_rate_limit(tenant_id: str = Depends(verificar_token)) -> str:
    if not tenant_rate_limiter.allow(tenant_id):
        logger.warning("Rate limit excedido para tenant_id=%s", tenant_id)
        raise HTTPException(
            status_code=429,
            detail="Limite de pedidos por minuto excedido para este tenant.",
        )
    return tenant_id

# ---------------------------------------------------------------------------
# auditoria
# ---------------------------------------------------------------------------

def log_audit_event(user_id: str, tenant_id: str, action: str, details: str = "") -> None:
    try:
        point = (
            Point("system_access_log")
            .tag("user_id", user_id)
            .tag("tenant_id", tenant_id)
            .field("action", action)
            .field("details", details)
        )
        get_influx_client().write_api().write(
            bucket=INFLUX_BUCKET,
            org=INFLUX_ORG,
            record=point,
        )
    except Exception as exc:
        print(f"Falha ao gravar evento de auditoria no InfluxDB: {exc}")
