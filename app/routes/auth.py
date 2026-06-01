"""
app/routes/auth.py
rotas de autenticacao: /login, /logout
"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt  # type: ignore

from config import ADMIN_TENANT_ID, ALGORITHM, SECRET_KEY
from app.dependencies import (
    criar_token_jwt,
    log_audit_event,
    login_rate_limiter,
    oauth2_scheme,
)
from app.services.database import get_db_connection, validar_tenant_id
import app.state as state

logger = logging.getLogger("metric4.api")

router = APIRouter()


@router.post("/login", tags=["Autenticacao"])
def login(
    credenciais: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    background_tasks: BackgroundTasks = None,
):
    """autentica utilizador e devolve jwt com role (superadmin | admin | user)"""
    if not login_rate_limiter.allow(credenciais.username):
        logger.warning("Rate limit de login excedido para username=%s", credenciais.username)
        raise HTTPException(status_code=429, detail="Demasiadas tentativas de login. Aguarde 1 minuto.")

    utilizador = state.UTILIZADORES.get(credenciais.username)
    if utilizador:
        if utilizador["password"] != credenciais.password:
            raise HTTPException(status_code=401, detail="Password incorreta.")
        tenant_id = utilizador["tenant_id"]
        role = "superadmin" if tenant_id == ADMIN_TENANT_ID else "user"
        subject = credenciais.username
        tenant_nome = tenant_id
        try:
            with get_db_connection() as conn:
                row = conn.execute("SELECT nome FROM clientes WHERE id = ?", (tenant_id,)).fetchone()
                tenant_nome = row["nome"] if row else tenant_id
        except Exception:
            pass
    else:
        try:
            with get_db_connection() as conn:
                cliente = conn.execute(
                    "SELECT id, nome FROM clientes WHERE nome = ? AND password = ?",
                    (credenciais.username, credenciais.password),
                ).fetchone()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Erro interno no login: {exc}")

        if not cliente:
            raise HTTPException(status_code=401, detail="Utilizador nao existe.")

        if cliente["id"] == ADMIN_TENANT_ID:
            raise HTTPException(
                status_code=403,
                detail="O cliente administrador autentica via conta de utilizador.",
            )

        tenant_id = cliente["id"]
        role = "admin"
        subject = credenciais.username
        tenant_nome = cliente["nome"]

    if not validar_tenant_id(tenant_id):
        logger.error("tenant_id invalido detectado no login: user=%s", credenciais.username)
        raise HTTPException(status_code=400, detail="Identificador de cliente invalido.")

    logger.info("Login bem-sucedido: user=%s tenant_id=%s role=%s", subject, tenant_id, role)
    background_tasks.add_task(log_audit_event, subject, tenant_id, "login", f"role={role}")

    logo_url = None
    try:
        with get_db_connection() as conn:
            row_logo = conn.execute(
                "SELECT logo_url FROM clientes WHERE id = ?", (tenant_id,)
            ).fetchone()
            logo_url = row_logo["logo_url"] if row_logo else None
    except Exception:
        pass

    token = criar_token_jwt({"sub": subject, "tenant_id": tenant_id, "role": role})
    return {
        "access_token": token,
        "token_type":   "bearer",
        "tenant_id":    tenant_id,
        "tenant_nome":  tenant_nome,
        "logo_url":     logo_url,
        "role":         role,
        "is_admin":     role == "superadmin",
        "mensagem":     f"Bem-vindo, {subject}.",
    }


@router.post("/logout", tags=["Autenticacao"])
def logout(
    background_tasks: BackgroundTasks,
    token: str = Depends(oauth2_scheme),
):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub", "desconhecido")
        tenant_id = payload.get("tenant_id", "desconhecido")
    except Exception:
        user_id = "desconhecido"
        tenant_id = "desconhecido"

    background_tasks.add_task(log_audit_event, user_id, tenant_id, "logout", "Logout de sessao")
    return {"sucesso": True}
