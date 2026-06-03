"""
app/routes/admin.py
rotas de administracao: /api/admin/* (tenants, users, mapas, tags)
"""

import logging
import re
import sqlite3
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from config import ADMIN_TENANT_ID, ADMIN_USERNAME
from app.dependencies import (
    _verificar_acesso_tenant,
    aplicar_rate_limit,
    log_audit_event,
    obter_payload_token,
    require_admin,
)
from app.models import (
    MapaCreate,
    MapaUpdate,
    TagAliasesUpdate,
    TagCreate,
    TenantCreate,
    TenantUpdate,
    UserCreate,
    UserUpdate,
)
from app.services.database import get_db_connection
import app.state as state

logger = logging.getLogger("metric4.api")

router = APIRouter()


@router.get("/api/admin/tenants", tags=["Admin"])
def admin_get_tenants(_: str = Depends(require_admin)):
    try:
        with get_db_connection() as conn:
            clientes = conn.execute("SELECT id, nome, password FROM clientes").fetchall()
            return [{"id": c["id"], "nome": c["nome"], "password": c["password"] or ""} for c in clientes]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao obter clientes: {exc}")


@router.get("/api/mapas", tags=["General"])
def obter_mapas_utilizador(tenant_id: str = Depends(aplicar_rate_limit)):
    try:
        with get_db_connection() as conn:
            mapas = conn.execute(
                "SELECT id, nome, limite_x, limite_y, ficheiro_img FROM mapas WHERE cliente_id = ?",
                (tenant_id,)
            ).fetchall()
            return [{"id": m["id"], "nome": m["nome"], "limite_x": m["limite_x"],
                     "limite_y": m["limite_y"], "path": m["ficheiro_img"]} for m in mapas]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao obter mapas: {exc}")


@router.get("/api/admin/config/{tenant_id}", tags=["Admin"])
def admin_get_config(tenant_id: str, payload: dict = Depends(obter_payload_token)):
    _verificar_acesso_tenant(tenant_id, payload)
    try:
        with get_db_connection() as conn:
            users = conn.execute("SELECT username FROM users WHERE cliente_id = ?", (tenant_id,)).fetchall()
            mapas = conn.execute(
                "SELECT id, nome, limite_x, limite_y, ficheiro_img FROM mapas WHERE cliente_id = ?",
                (tenant_id,)
            ).fetchall()
            tags = conn.execute("SELECT id_fisico, nome FROM tags WHERE cliente_id = ?", (tenant_id,)).fetchall()
            return {
                "tenant_id": tenant_id,
                "users": [u["username"] for u in users],
                "mapas": [{"id": m["id"], "nome": m["nome"], "limite_x": m["limite_x"],
                           "limite_y": m["limite_y"], "path": m["ficheiro_img"]} for m in mapas],
                "tags": [{"tag_id": t["id_fisico"], "friendly_name": t["nome"]} for t in tags],
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao obter config: {exc}")


@router.post("/api/admin/mapas", tags=["Admin"])
def admin_create_mapa(data: MapaCreate, background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    _verificar_acesso_tenant(data.tenant_id, payload)
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO mapas (nome, limite_x, limite_y, ficheiro_img, cliente_id) VALUES (?, ?, ?, ?, ?)",
                (data.nome, data.limite_x, data.limite_y, data.ficheiro_img, data.tenant_id)
            )
            conn.commit()
        background_tasks.add_task(
            log_audit_event, admin_tenant, data.tenant_id, "map_created",
            f"Mapa '{data.nome}' criado (Dimensoes: {data.limite_x}x{data.limite_y} cm, Imagem: {data.ficheiro_img or 'Nenhuma'})",
        )
        return {"sucesso": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao criar mapa: {exc}")


@router.put("/api/admin/mapas/{map_id}", tags=["Admin"])
def admin_update_mapa(map_id: int, data: MapaUpdate, background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT cliente_id, nome, limite_x, limite_y, ficheiro_img FROM mapas WHERE id = ?", (map_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Mapa nao encontrado.")
            _verificar_acesso_tenant(row["cliente_id"], payload)
            conn.execute(
                "UPDATE mapas SET nome = ?, limite_x = ?, limite_y = ?, ficheiro_img = ? WHERE id = ?",
                (data.nome, data.limite_x, data.limite_y, data.ficheiro_img, map_id)
            )
            conn.commit()
        old_state = f"[{row['nome']} | {row['limite_x']}x{row['limite_y']} | {row['ficheiro_img'] or 'Sem IMG'}]"
        new_state = f"[{data.nome} | {data.limite_x}x{data.limite_y} | {data.ficheiro_img or 'Sem IMG'}]"
        background_tasks.add_task(
            log_audit_event, admin_tenant, row["cliente_id"], "map_updated",
            f"Mapa ID:{map_id} atualizado. ANTES: {old_state} -> DEPOIS: {new_state}",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao atualizar mapa: {exc}")


@router.delete("/api/admin/mapas/{map_id}", tags=["Admin"])
def admin_delete_mapa(map_id: int, background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT cliente_id, nome FROM mapas WHERE id = ?", (map_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Mapa nao encontrado.")
            _verificar_acesso_tenant(row["cliente_id"], payload)
            conn.execute("DELETE FROM ancoras WHERE mapa_id = ?", (map_id,))
            conn.execute("DELETE FROM mapas WHERE id = ?", (map_id,))
            conn.commit()
        background_tasks.add_task(
            log_audit_event, admin_tenant, row["cliente_id"], "map_deleted",
            f"Mapa '{row['nome']}' (ID: {map_id}) e todas as suas ancoras apagados.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao apagar mapa: {exc}")


@router.post("/api/admin/tags/aliases", tags=["Admin"])
def admin_update_aliases(data: TagAliasesUpdate, background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    if payload.get("role") not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Acesso negado.")
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            for tag in data.tags:
                if payload.get("role") == "admin":
                    conn.execute("UPDATE tags SET nome = ? WHERE id_fisico = ? AND cliente_id = ?",
                                 (tag.friendly_name, tag.tag_id, admin_tenant))
                else:
                    conn.execute("UPDATE tags SET nome = ? WHERE id_fisico = ?",
                                 (tag.friendly_name, tag.tag_id))
            conn.commit()
        aliases_log = ", ".join([f"[{t.tag_id} -> '{t.friendly_name}']" for t in data.tags])
        background_tasks.add_task(
            log_audit_event, admin_tenant, admin_tenant, "tag_aliases_updated",
            f"Nomes de {len(data.tags)} tags atualizados: {aliases_log}",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao atualizar tags: {exc}")


@router.post("/api/admin/tenants", tags=["Admin"])
def admin_create_tenant(data: TenantCreate, background_tasks: BackgroundTasks, admin_tenant: str = Depends(require_admin)):
    try:
        with get_db_connection() as conn:
            clean_name = re.sub(r"[^a-z0-9]", "_", data.nome.lower())
            clean_name = re.sub(r"_+", "_", clean_name).strip("_")[:10]
            suffix = uuid.uuid4().hex[:6]
            novo_id = f"{clean_name}_{suffix}" if clean_name else f"tenant_{suffix}"
            conn.execute("INSERT INTO clientes (id, nome, password) VALUES (?, ?, ?)",
                         (novo_id, data.nome, data.password or None))
            conn.commit()
        background_tasks.add_task(
            log_audit_event, admin_tenant, novo_id, "tenant_created",
            f"Cliente '{data.nome}' criado com sucesso (ID: {novo_id}).",
        )
        return {"sucesso": True, "id": novo_id}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Erro interno ao gerar ID.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")


@router.put("/api/admin/tenants/{tenant_id}", tags=["Admin"])
def admin_update_tenant(tenant_id: str, data: TenantUpdate, background_tasks: BackgroundTasks, admin_tenant: str = Depends(require_admin)):
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT nome FROM clientes WHERE id = ?", (tenant_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Cliente nao encontrado.")
            if data.password is not None:
                conn.execute("UPDATE clientes SET nome = ?, password = ? WHERE id = ?",
                             (data.nome, data.password or None, tenant_id))
            else:
                conn.execute("UPDATE clientes SET nome = ? WHERE id = ?", (data.nome, tenant_id))
            conn.commit()
        pass_mudou = "Sim" if data.password else "Nao"
        background_tasks.add_task(
            log_audit_event, admin_tenant, tenant_id, "tenant_updated",
            f"Cliente ID: {tenant_id} atualizado. Nome alterado de '{row['nome']}' para '{data.nome}'. Password Alterada: {pass_mudou}.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")


@router.delete("/api/admin/tenants/{tenant_id}", tags=["Admin"])
def admin_delete_tenant(tenant_id: str, background_tasks: BackgroundTasks, admin_tenant: str = Depends(require_admin)):
    if tenant_id == ADMIN_TENANT_ID:
        raise HTTPException(status_code=400, detail="Nao pode apagar o utilizador administrador do sistema.")
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT nome FROM clientes WHERE id = ?", (tenant_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Cliente nao encontrado.")
            conn.execute("DELETE FROM tags WHERE cliente_id = ?", (tenant_id,))
            conn.execute("DELETE FROM users WHERE cliente_id = ?", (tenant_id,))
            mapas = conn.execute("SELECT id FROM mapas WHERE cliente_id = ?", (tenant_id,)).fetchall()
            for mapa in mapas:
                conn.execute("DELETE FROM ancoras WHERE mapa_id = ?", (mapa["id"],))
            conn.execute("DELETE FROM mapas WHERE cliente_id = ?", (tenant_id,))
            conn.execute("DELETE FROM clientes WHERE id = ?", (tenant_id,))
            conn.commit()
            state.reload_utilizadores()
        background_tasks.add_task(
            log_audit_event, admin_tenant, tenant_id, "tenant_deleted",
            f"Cliente '{row['nome']}' (ID: {tenant_id}) apagado e todos os seus dados eliminados em cascata.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")


@router.post("/api/admin/users", tags=["Admin"])
def admin_create_user(data: UserCreate, background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    _verificar_acesso_tenant(data.tenant_id, payload)
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            existing_user = conn.execute(
                "SELECT u.username, c.nome as cliente_nome FROM users u JOIN clientes c ON u.cliente_id = c.id WHERE u.username = ?",
                (data.username,)
            ).fetchone()
            if existing_user:
                raise HTTPException(status_code=400, detail=f"O username '{data.username}' ja esta em uso no cliente '{existing_user['cliente_nome']}'.")
            conn.execute("INSERT INTO users (username, password, cliente_id) VALUES (?, ?, ?)",
                         (data.username, data.password, data.tenant_id))
            conn.commit()
            state.reload_utilizadores()
        background_tasks.add_task(
            log_audit_event, admin_tenant, data.tenant_id, "user_created",
            f"Utilizador '{data.username}' criado para este cliente.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="O username ja existe.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")


@router.put("/api/admin/users/{username}", tags=["Admin"])
def admin_update_user(username: str, data: UserUpdate, background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    if username == ADMIN_USERNAME and data.new_username and data.new_username != ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="Nao pode alterar o username da conta admin principal.")
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            db_user = conn.execute("SELECT password, cliente_id FROM users WHERE username = ?", (username,)).fetchone()
            if not db_user:
                raise HTTPException(status_code=404, detail="Utilizador nao encontrado.")
            _verificar_acesso_tenant(db_user["cliente_id"], payload)
            if data.new_username and data.new_username != username:
                existing_user = conn.execute(
                    "SELECT u.username, c.nome as cliente_nome FROM users u JOIN clientes c ON u.cliente_id = c.id WHERE u.username = ?",
                    (data.new_username,)
                ).fetchone()
                if existing_user:
                    raise HTTPException(status_code=400, detail=f"O novo username '{data.new_username}' ja esta a ser utilizado.")
            novo_user = data.new_username if data.new_username else username
            nova_pass = data.password if data.password else db_user["password"]
            pass_mudou = "Sim" if data.password else "Nao"
            conn.execute("UPDATE users SET username = ?, password = ? WHERE username = ?", (novo_user, nova_pass, username))
            conn.commit()
            state.reload_utilizadores()
        background_tasks.add_task(
            log_audit_event, admin_tenant, db_user["cliente_id"], "user_updated",
            f"Utilizador '{username}' atualizado. Novo Username: '{novo_user}', Password Alterada: {pass_mudou}.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="O novo username ja esta em uso.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")


@router.delete("/api/admin/users/{username}", tags=["Admin"])
def admin_delete_user(username: str, background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    if username == ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="Nao pode apagar a conta admin.")
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT cliente_id FROM users WHERE username = ?", (username,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Utilizador nao encontrado.")
            _verificar_acesso_tenant(row["cliente_id"], payload)
            conn.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()
            state.reload_utilizadores()
        background_tasks.add_task(
            log_audit_event, admin_tenant, row["cliente_id"], "user_deleted",
            f"Utilizador '{username}' apagado permanentemente.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")


@router.post("/api/admin/tags", tags=["Admin"])
def admin_create_tag(data: TagCreate, background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    _verificar_acesso_tenant(data.tenant_id, payload)
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO tags (id_fisico, nome, cliente_id) VALUES (?, ?, ?)",
                         (data.tag_id, data.nome, data.tenant_id))
            conn.commit()
        background_tasks.add_task(
            log_audit_event, admin_tenant, data.tenant_id, "tag_created",
            f"Nova Tag monitorizada: ID Fisico '{data.tag_id}', Nome Amigavel '{data.nome}'.",
        )
        return {"sucesso": True}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Tag ja existe.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")


@router.delete("/api/admin/tags/{tag_id}", tags=["Admin"])
def admin_delete_tag(tag_id: str, background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT cliente_id FROM tags WHERE id_fisico = ?", (tag_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tag nao encontrada.")
            _verificar_acesso_tenant(row["cliente_id"], payload)
            conn.execute("DELETE FROM tags WHERE id_fisico = ?", (tag_id,))
            conn.commit()
        background_tasks.add_task(
            log_audit_event, admin_tenant, row["cliente_id"], "tag_deleted",
            f"Tag '{tag_id}' apagada permanentemente.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")
