"""
app/routes/tenant.py
rotas do perfil do tenant e credenciais do utilizador:
/api/tenant/*, /api/user/credentials
"""

import logging
import sqlite3
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from app.dependencies import log_audit_event, obter_payload_token
from app.models import SelfCredentialsUpdate, TenantProfileUpdate
from app.services.database import get_db_connection
import app.state as state

logger = logging.getLogger("metric4.api")

router = APIRouter()

AVATARS_FS_DIR = Path(__file__).parent.parent.parent / "frontend" / "assets" / "imgs" / "avatars"
AVATARS_URL_PREFIX = "/static/assets/imgs/avatars/"
ALLOWED_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_AVATAR_BYTES = 2 * 1024 * 1024


def _require_tenant_admin(payload: dict) -> str:
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Apenas o administrador da empresa pode alterar estes dados.")
    return payload["tenant_id"]


def _cliente_row_ou_404(conn: sqlite3.Connection, tenant_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT id, nome, password, logo_url FROM clientes WHERE id = ?", (tenant_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cliente nao encontrado.")
    return row


def _extensao_avatar_por_conteudo(conteudo: bytes, filename: str = "") -> str:
    if conteudo.startswith(b"\x89PNG\r\n\x1a\n") or conteudo.startswith(b"\x89PNG"):
        return ".png"
    if conteudo.startswith(b"\xff\xd8"):
        return ".jpg"
    if len(conteudo) >= 12 and conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP":
        return ".webp"
    nome = (filename or "").lower()
    if nome.endswith(".png"):
        return ".png"
    if nome.endswith(".webp"):
        return ".webp"
    if nome.endswith((".jpg", ".jpeg")):
        return ".jpg"
    raise HTTPException(status_code=400, detail="Formato nao suportado. Envie PNG, JPEG ou WebP.")


def _remover_ficheiros_avatar(tenant_id: str) -> None:
    AVATARS_FS_DIR.mkdir(parents=True, exist_ok=True)
    for ficheiro in AVATARS_FS_DIR.glob(f"{tenant_id}.*"):
        if ficheiro.is_file():
            ficheiro.unlink(missing_ok=True)


def _logo_url_canonica(tenant_id: str, ext: str) -> str:
    return f"{AVATARS_URL_PREFIX}{tenant_id}{ext}"


@router.get("/api/tenant/branding", tags=["Tenant"])
def obter_tenant_branding(payload: dict = Depends(obter_payload_token)):
    tenant_id = payload["tenant_id"]
    with get_db_connection() as conn:
        row = _cliente_row_ou_404(conn, tenant_id)
    return {"tenant_id": row["id"], "nome": row["nome"], "logo_url": row["logo_url"]}


@router.put("/api/tenant/profile", tags=["Tenant"])
def atualizar_tenant_profile(
    data: TenantProfileUpdate,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    tenant_id = _require_tenant_admin(payload)
    subject = payload.get("sub", "")

    if not data.nome and not data.new_password:
        raise HTTPException(status_code=400, detail="Indica pelo menos um campo a alterar.")

    with get_db_connection() as conn:
        row = _cliente_row_ou_404(conn, tenant_id)
        if data.current_password != row["password"]:
            raise HTTPException(status_code=400, detail="Password atual incorreta.")

        novo_nome = data.nome.strip() if data.nome else row["nome"]
        if not novo_nome:
            raise HTTPException(status_code=400, detail="O nome do cliente nao pode estar vazio.")

        nova_pass = data.new_password if data.new_password else row["password"]
        conn.execute("UPDATE clientes SET nome = ?, password = ? WHERE id = ?",
                     (novo_nome, nova_pass, tenant_id))
        conn.commit()

    pass_mudou = "Sim" if data.new_password else "Nao"
    background_tasks.add_task(
        log_audit_event, subject, tenant_id, "tenant_profile_updated",
        f"Nome: '{novo_nome}', Password alterada: {pass_mudou}.",
    )
    return {"sucesso": True, "tenant_id": tenant_id, "nome": novo_nome, "nome_alterado": novo_nome != row["nome"]}


@router.post("/api/tenant/profile/avatar", tags=["Tenant"])
async def upload_tenant_avatar(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    payload: dict = Depends(obter_payload_token),
):
    tenant_id = _require_tenant_admin(payload)
    subject = payload.get("sub", "")

    conteudo = await file.read()
    if len(conteudo) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Imagem demasiado grande (maximo 2 MB).")
    if len(conteudo) < 100:
        raise HTTPException(status_code=400, detail="Ficheiro de imagem invalido ou vazio.")

    ext = _extensao_avatar_por_conteudo(conteudo, file.filename or "")
    if ext not in ALLOWED_AVATAR_EXT:
        raise HTTPException(status_code=400, detail="Extensao de ficheiro nao permitida.")

    AVATARS_FS_DIR.mkdir(parents=True, exist_ok=True)
    _remover_ficheiros_avatar(tenant_id)
    destino = AVATARS_FS_DIR / f"{tenant_id}{ext}"
    destino.write_bytes(conteudo)

    logo_url = _logo_url_canonica(tenant_id, ext)
    with get_db_connection() as conn:
        _cliente_row_ou_404(conn, tenant_id)
        conn.execute("UPDATE clientes SET logo_url = ? WHERE id = ?", (logo_url, tenant_id))
        conn.commit()

    background_tasks.add_task(log_audit_event, subject, tenant_id, "tenant_avatar_uploaded",
                               f"Avatar actualizado: {logo_url}")
    return {"sucesso": True, "logo_url": logo_url}


@router.delete("/api/tenant/profile/avatar", tags=["Tenant"])
def remover_tenant_avatar(background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    tenant_id = _require_tenant_admin(payload)
    subject = payload.get("sub", "")

    _remover_ficheiros_avatar(tenant_id)
    with get_db_connection() as conn:
        _cliente_row_ou_404(conn, tenant_id)
        conn.execute("UPDATE clientes SET logo_url = NULL WHERE id = ?", (tenant_id,))
        conn.commit()

    background_tasks.add_task(log_audit_event, subject, tenant_id, "tenant_avatar_removed",
                               "Avatar da empresa removido.")
    return {"sucesso": True, "logo_url": None}


@router.put("/api/user/credentials", tags=["User"])
def update_self_credentials(
    data: SelfCredentialsUpdate,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    if payload.get("role") == "admin":
        raise HTTPException(status_code=403, detail="Conta ADMIN nao tem credenciais na tabela de utilizadores.")
    current_username: str = payload.get("sub", "")
    if not current_username:
        raise HTTPException(status_code=401, detail="Token invalido")

    with get_db_connection() as conn:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (current_username,)).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="Utilizador nao encontrado")

        if data.current_password != user["password"]:
            raise HTTPException(status_code=400, detail="Password atual incorreta")

        if data.new_username and data.new_username != current_username:
            conflito = conn.execute(
                "SELECT u.username, c.nome AS tenant_nome FROM users u JOIN clientes c ON u.cliente_id = c.id WHERE u.username = ?",
                (data.new_username,)
            ).fetchone()
            if conflito:
                raise HTTPException(
                    status_code=400,
                    detail=f"Username '{data.new_username}' ja existe (empresa: {conflito['tenant_nome']})"
                )

        new_name = data.new_username or current_username
        new_password = data.new_password if data.new_password else user["password"]

        conn.execute("UPDATE users SET username = ?, password = ? WHERE username = ?",
                     (new_name, new_password, current_username))
        conn.commit()
        state.reload_utilizadores()

        pass_mudou = "Sim" if data.new_password else "Nao"
        background_tasks.add_task(
            log_audit_event, current_username, user["cliente_id"], "credentials_updated",
            f"O utilizador atualizou os seus dados. Novo Username: '{new_name}', Password Alterada: {pass_mudou}."
        )

        username_changed = bool(data.new_username and data.new_username != current_username)
        return {"sucesso": True, "username_changed": username_changed}
