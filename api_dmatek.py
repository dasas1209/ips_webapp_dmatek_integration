"""
api_dmatek.py
api rest do sistema metric4 rtls
"""
import logging
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import List, Optional
import uuid
from pydantic import BaseModel

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from influxdb_client import Point  # type: ignore
from jose import JWTError, jwt  # type: ignore

from config import (
    ALGORITHM,
    ALLOWED_ORIGINS,
    INFLUX_BUCKET,
    INFLUX_ORG,
    JANELA_KPI_HORAS,
    LIMITE_DIAS_HISTORICO,
    SECRET_KEY,
    TOKEN_EXPIRY_HOURS,
    ADMIN_TENANT_ID,
    ADMIN_USERNAME,
)
from services.database import (
    DB_PATH,
    get_db_connection,
    obter_limites_mapa,
    validar_tenant_id,
)
from services.influx_client import get_influx_client
from services.kpi_engine import KpiTag, RegistoTag, calcular_kpis

# configuracao da aplicacao fastapi

app = FastAPI(
    title="Portal de Dados RTLS — Metric4",
    description="API de Gestão Multi-Tenant para posições em tempo real.",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")

# versão das rotas de perfil do tenant (health check no frontend)
API_BUILD_ID = "2026-06-01-password-crud-v3"


@app.on_event("startup")
async def _log_startup() -> None:
    tenant_routes = sorted(
        r.path for r in app.routes
        if hasattr(r, "path") and isinstance(r.path, str) and r.path.startswith("/api/tenant/")
    )
    logger.info("API build %s | rotas tenant: %s", API_BUILD_ID, tenant_routes)


@app.get("/api/health", include_in_schema=False)
def api_health():
    """permite ao frontend confirmar que a API em execução inclui as rotas de perfil."""
    return {"ok": True, "build": API_BUILD_ID, "tenant_profile_api": True}

# logging de seguranca (sem coordenadas para minimizar exposição de localização)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("metric4.api")

# avatares de clientes (ficheiro: {tenant_id}.<ext>, URL em clientes.logo_url)
AVATARS_FS_DIR = Path(__file__).parent / "frontend" / "assets" / "imgs" / "avatars"
AVATARS_URL_PREFIX = "/static/assets/imgs/avatars/"
ALLOWED_AVATAR_MIME = {"image/png", "image/jpeg", "image/webp"}
ALLOWED_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MAX_AVATAR_BYTES = 2 * 1024 * 1024


# serving de paginas html

_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}


@app.get("/", include_in_schema=False)
@app.get("/app", include_in_schema=False)
async def serve_index():
    return FileResponse("frontend/index.html", headers=_NO_CACHE)


@app.get("/relatorio.html", include_in_schema=False)
async def serve_relatorio():
    return FileResponse("frontend/relatorio.html", headers=_NO_CACHE)


@app.get("/auditoria.html", include_in_schema=False)
async def serve_auditoria():
    return FileResponse("frontend/auditoria.html", headers=_NO_CACHE)


@app.get("/admin.html", include_in_schema=False)
async def serve_admin():
    return FileResponse("frontend/admin.html", headers=_NO_CACHE)


@app.get("/app/audit-log", include_in_schema=False)
async def serve_audit_log():
    return FileResponse("frontend/audit_log.html", headers=_NO_CACHE)


# carregamento de utilizadores da base de dados

def carregar_utilizadores_db() -> dict[str, dict]:
    """carrega utilizadores da bd sqlite"""
    utilizadores: dict[str, dict] = {}
    try:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT username, password, cliente_id FROM users"
            ).fetchall()
        for row in rows:
            utilizadores[row["username"]] = {
                "password":  row["password"],
                "tenant_id": row["cliente_id"],
            }
        if not utilizadores:
            raise RuntimeError(
                "Tabela users vazia. Corre database_setup.py antes de iniciar a API."
            )
        logger.info("Utilizadores carregados da BD: %s", len(utilizadores))
    except sqlite3.Error as exc:
        raise RuntimeError(
            f"Falha ao ler utilizadores da BD ({DB_PATH.resolve()}): {exc}. "
            "Corre database_setup.py ou reinicia a API após migração."
        ) from exc
    return utilizadores


UTILIZADORES: dict[str, dict] = carregar_utilizadores_db()


# throttling por tenant/username

class TenantRateLimiter:
    """throttling em memória por chave para reduzir risco de noisy neighbor e brute force"""

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


# throttling para endpoints autenticados (por tenant)
tenant_rate_limiter = TenantRateLimiter(max_requests=120, window_seconds=60)

# throttling para /login (por username) — previne brute force
# futuro: substituir chave por ip (request.client.host) quando em ambiente de producao
login_rate_limiter = TenantRateLimiter(max_requests=10, window_seconds=60)


# configuracao de seguranca jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def criar_token_jwt(dados: dict) -> str:
    """gera jwt assinado"""
    payload = dados.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)  # type: ignore


def obter_payload_token(token: str = Depends(oauth2_scheme)) -> dict:
    """decodifica jwt e devolve payload completo"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])  # type: ignore
        if not payload.get("tenant_id"):
            raise HTTPException(status_code=401, detail="Token sem identificação de cliente.")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Acesso negado: token inválido ou expirado.")


def verificar_token(payload: dict = Depends(obter_payload_token)) -> str:
    """devolve tenant_id do token — mantém compatibilidade com aplicar_rate_limit"""
    return payload["tenant_id"]


# ---------------------------------------------------------------------------
# dependencias de roles
# ---------------------------------------------------------------------------

def require_admin(payload: dict = Depends(obter_payload_token)) -> str:
    """garante role=superadmin; devolve tenant_id para compatibilidade com call sites existentes"""
    if payload.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Acesso negado: apenas o administrador do sistema.")
    return payload["tenant_id"]


def require_superadmin(payload: dict = Depends(obter_payload_token)) -> dict:
    """garante role=superadmin; devolve payload completo."""
    if payload.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="Acesso negado: apenas superadmin.")
    return payload


def _verificar_acesso_tenant(tenant_alvo: str, payload: dict) -> None:
    """superadmin acessa qualquer tenant; admin só acessa o próprio."""
    role = payload.get("role")
    if role == "superadmin":
        return
    if role == "admin" and payload.get("tenant_id") == tenant_alvo:
        return
    raise HTTPException(status_code=403, detail="Acesso negado: sem permissão para este tenant.")


def log_audit_event(user_id: str, tenant_id: str, action: str, details: str = "") -> None:
    """regista eventos no InfluxDB sem bloquear a rota principal."""
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


def aplicar_rate_limit(tenant_id: str = Depends(verificar_token)) -> str:
    """aplica throttling por tenant em endpoints autenticados"""
    if not tenant_rate_limiter.allow(tenant_id):
        logger.warning("Rate limit excedido para tenant_id=%s", tenant_id)
        raise HTTPException(
            status_code=429,
            detail="Limite de pedidos por minuto excedido para este tenant.",
        )
    return tenant_id


# rotas de autenticacao

@app.post("/login", tags=["Autenticação"])
def login(
    credenciais: OAuth2PasswordRequestForm = Depends(),
    request: Request = None,
    background_tasks: BackgroundTasks = None,
):
    """autentica utilizador e devolve jwt com role (superadmin | admin | user)"""
    if not login_rate_limiter.allow(credenciais.username):
        logger.warning("Rate limit de login excedido para username=%s", credenciais.username)
        raise HTTPException(status_code=429, detail="Demasiadas tentativas de login. Aguarde 1 minuto.")

    # --- tentativa 1: tabela users (role=superadmin ou role=user) ---
    utilizador = UTILIZADORES.get(credenciais.username)
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
        # --- tentativa 2: tabela clientes por nome (role=admin) ---
        try:
            with get_db_connection() as conn:
                cliente = conn.execute(
                    "SELECT id, nome FROM clientes WHERE nome = ? AND password = ?",
                    (credenciais.username, credenciais.password),
                ).fetchone()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Erro interno no login: {exc}")

        if not cliente:
            raise HTTPException(status_code=401, detail="Utilizador não existe.")

        # o cliente_admin só autentica via tabela users — impede escalada de privilégios
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
        raise HTTPException(status_code=400, detail="Identificador de cliente inválido.")

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
        "is_admin":     role == "superadmin",  # retro-compatibilidade com frontend atual
        "mensagem":     f"Bem-vindo, {subject}.",
    }


@app.post("/logout", tags=["Autenticação"])
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
        
    background_tasks.add_task(
        log_audit_event,
        user_id,
        tenant_id,
        "logout",
        "Logout de sessão",
    )
    return {"sucesso": True}


# rotas de tempo real

@app.get("/posicoes", tags=["Real-Time"])
def obter_posicoes(tenant_id: str = Depends(aplicar_rate_limit)):
    """devolve ultima posicao conhecida de cada tag"""
    try:
        query = f"""
            from(bucket: "{INFLUX_BUCKET}")
            |> range(start: -1h)
            |> filter(fn: (r) => r["_measurement"] == "posicao_tag")
            |> filter(fn: (r) => r["tenant_id"] == "{tenant_id}")
            |> last()
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        """
        tabelas = get_influx_client().query_api().query(query)

        posicoes = []
        for tabela in tabelas:
            for linha in tabela.records:
                x = linha.values.get("coord_x")
                y = linha.values.get("coord_y")
                if x is None or y is None:
                    continue
                posicoes.append({
                    "tag_id":    linha.values.get("tag_id"),
                    "x":         x,
                    "y":         y,
                    "timestamp": linha.values.get("_time"),
                    "bateria":   linha.values.get("bateria") or 0,
                    "status":    linha.values.get("status") or "Urgency",
                })

        try:
            with get_db_connection() as conn:
                tags_db = conn.execute("SELECT id_fisico, nome FROM tags WHERE cliente_id = ?", (tenant_id,)).fetchall()
                total_sql = len(tags_db)
                nome_por_tag = {t["id_fisico"]: t["nome"] for t in tags_db}
        except Exception:
            total_sql = len(posicoes)
            nome_por_tag = {}

        # Add friendly names to positions
        for p in posicoes:
            p["nome"] = nome_por_tag.get(p["tag_id"], p["tag_id"])

        return {
            "tenant_id":            tenant_id,
            "total_tags_detetadas": len(posicoes),
            "total_tags_sql":       total_sql,
            "dados":                posicoes,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar posições: {exc}")


@app.get("/historico", tags=["Real-Time"])
def obter_historico(
    minutos_atras: int = Query(..., ge=1, le=480, description="Minutos a recuar (1–480)"),
    tenant_id: str = Depends(aplicar_rate_limit),
):
    """devolve posicoes num instante historico especifico"""
    try:
        query = f"""
            from(bucket: "{INFLUX_BUCKET}")
            |> range(start: -{minutos_atras}m10s, stop: -{minutos_atras}m)
            |> filter(fn: (r) => r["_measurement"] == "posicao_tag")
            |> filter(fn: (r) => r["tenant_id"] == "{tenant_id}")
            |> last()
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        """
        tabelas = get_influx_client().query_api().query(query)

        posicoes = []
        for tabela in tabelas:
            for linha in tabela.records:
                x = linha.values.get("coord_x")
                y = linha.values.get("coord_y")
                if x is None or y is None:
                    continue
                posicoes.append({
                    "tag_id":    linha.values.get("tag_id"),
                    "x":         x,
                    "y":         y,
                    "timestamp": linha.values.get("_time"),
                    "bateria":   linha.values.get("bateria") or 0,
                    "status":    linha.values.get("status") or "Urgency",
                })

        try:
            with get_db_connection() as conn:
                tags_db = conn.execute("SELECT id_fisico, nome FROM tags WHERE cliente_id = ?", (tenant_id,)).fetchall()
                nome_por_tag = {t["id_fisico"]: t["nome"] for t in tags_db}
        except Exception:
            nome_por_tag = {}

        for p in posicoes:
            p["nome"] = nome_por_tag.get(p["tag_id"], p["tag_id"])

        return {
            "tenant_id":            tenant_id,
            "total_tags_detetadas": len(posicoes),
            "dados":                posicoes,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar histórico: {exc}")


# rotas de kpis


def _registos_de_tabelas_influx(resultado) -> list[RegistoTag]:
    """converte resultado flux numa lista de RegistoTag para o kpi_engine"""
    registos: list[RegistoTag] = []
    for table in resultado:
        for record in table.records:
            tag_id  = record.values.get("tag_id")
            x       = record.values.get("coord_x")
            y       = record.values.get("coord_y")
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
    """calcula kpis da frota no turno actual"""
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
        taxa_utilizacao = 0.0
        total_leituras  = sum(t.leituras_totais for t in tags.values())
        total_movimento = sum(t.leituras_em_movimento for t in tags.values())
        if total_leituras > 0:
            taxa_utilizacao = round((total_movimento / total_leituras) * 100, 1)

        baterias = [t.bateria_ultima for t in tags.values() if t.bateria_ultima > 0]
        bateria_media = round(sum(baterias) / len(baterias), 1) if baterias else 0.0

        # total de tags registadas na bd (independente da actividade influx)
        try:
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM tags WHERE cliente_id = ?",
                    (tenant_id,),
                ).fetchone()
            total_assets_bd = row["n"] if row else 0
        except Exception:
            total_assets_bd = len(tags)

        return {
            "sucesso":    True,
            "tenant_id":  tenant_id,
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


@app.get("/kpis", tags=["KPIs"])
async def obter_kpis_turno(tenant_id: str = Depends(aplicar_rate_limit)):
    """devolve kpis usando tenant extraído do token"""
    logger.info("Consulta de KPIs para tenant_id=%s", tenant_id)
    return await _obter_kpis_turno_por_tenant(tenant_id)


@app.get("/kpis/{tenant_id}", tags=["KPIs"], include_in_schema=False)
async def obter_kpis_turno_legado(
    tenant_id: str,
    token_tenant: str = Depends(aplicar_rate_limit),
):
    """rota legacy: mantém compatibilidade sem permitir troca de tenant"""
    if tenant_id != token_tenant:
        raise HTTPException(
            status_code=403,
            detail="Acesso negado: não tem permissão para ver os KPIs deste cliente.",
        )
    logger.info("Consulta de KPIs (legacy) para tenant_id=%s", token_tenant)
    return await _obter_kpis_turno_por_tenant(token_tenant)


# rotas de auditoria


def _eventos_auditoria_influx_para_incidentes(
    tabelas,
    limite_x: float,
    limite_y: float,
) -> list[dict]:
    """converte resultados flux da measurement evento_auditoria para o formato da lista incidentes"""
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


@app.get("/relatorio/dados", tags=["Auditoria"])
def obter_dados_auditoria(
    inicio: str = Query(..., description="Início ISO 8601, ex: 2026-05-11T06:00:00Z"),
    fim:    str = Query(..., description="Fim ISO 8601, ex: 2026-05-11T14:00:00Z"),
    tenant_id: str = Depends(aplicar_rate_limit),
):
    """consulta fluxo temporal completo para dashboard de auditoria"""

    # valida intervalo temporal
    try:
        dt_inicio = datetime.fromisoformat(inicio.replace("Z", "+00:00"))
        dt_fim    = datetime.fromisoformat(fim.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Formato de data inválido. Use ISO 8601, ex: 2026-05-11T06:00:00Z",
        )

    if dt_fim <= dt_inicio:
        raise HTTPException(status_code=422, detail="'fim' deve ser posterior a 'inicio'.")

    if (dt_fim - dt_inicio).days > LIMITE_DIAS_HISTORICO:
        raise HTTPException(
            status_code=422,
            detail=f"Intervalo máximo permitido: {LIMITE_DIAS_HISTORICO} dias.",
        )

    agora_utc = datetime.now(timezone.utc)
    if dt_inicio < agora_utc - timedelta(days=LIMITE_DIAS_HISTORICO):
        raise HTTPException(
            status_code=422,
            detail=f"'inicio' não pode ser anterior a {LIMITE_DIAS_HISTORICO} dias atrás.",
        )

    # usa datetime convertidos e validados
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
        # limites do mapa do cliente — usados para normalizar coordenadas (fix IMP-06)
        limite_x, limite_y = obter_limites_mapa(tenant_id)

        qa = get_influx_client().query_api()
        resultado         = qa.query(org=INFLUX_ORG, query=query_trajetoria)
        resultado_eventos = qa.query(org=INFLUX_ORG, query=query_eventos_auditoria)

        esparguete_pontos: list[dict] = []
        incidentes:        list[dict] = []

        # converte registos influx e calcula kpis via kpi_engine
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

                # normaliza com os limites do mapa do cliente
                x_norm = round(x_cm / limite_x, 5)
                y_norm = round(y_cm / limite_y, 5)
                ts_iso = ts.isoformat() if ts else None

                esparguete_pontos.append({"tag_id": tag_id, "x": x_norm, "y": y_norm, "t": ts_iso})

                registos.append(RegistoTag(
                    tag_id=tag_id,
                    x=x_cm,
                    y=y_cm,
                    timestamp=ts,
                    bateria=bateria,
                ))

        # calcula kpis por tag via motor partilhado
        tags = calcular_kpis(registos)

        # agrega eventos de auditoria — fonte exclusiva de incidentes
        # (evita duplicacao com o campo status da measurement posicao_tag)
        incidentes: list[dict] = []
        try:
            incidentes = _eventos_auditoria_influx_para_incidentes(
                resultado_eventos, limite_x, limite_y
            )
        except Exception:
            logger.exception("falha ao agregar eventos evento_auditoria do influx")

        incidentes.sort(key=lambda x: x.get("timestamp", ""))

        # conta alertas por tag apos consolidacao completa dos incidentes
        alertas_por_tag = Counter(inc["tag_id"] for inc in incidentes)

        distancia_frota_m    = 0.0
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

        bateria_media_frota = 0.0
        if baterias_para_media:
            bateria_media_frota = round(sum(baterias_para_media) / len(baterias_para_media), 1)


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
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao gerar dados de auditoria: {exc}",
        )


# rotas de administracao

class MapaCreate(BaseModel):
    nome: str
    limite_x: float
    limite_y: float
    ficheiro_img: Optional[str] = None
    tenant_id: str

class MapaUpdate(BaseModel):
    nome: str
    limite_x: float
    limite_y: float
    ficheiro_img: Optional[str] = None

class TagAliasUpdate(BaseModel):
    tag_id: str
    friendly_name: str

class TagAliasesUpdate(BaseModel):
    tags: List[TagAliasUpdate]

class TenantCreate(BaseModel):
    nome: str
    password: Optional[str] = None

class TenantUpdate(BaseModel):
    nome: str
    password: Optional[str] = None

class UserCreate(BaseModel):
    username: str
    password: str
    tenant_id: str

class UserUpdate(BaseModel):
    new_username: Optional[str] = None
    password: Optional[str] = None

class TagCreate(BaseModel):
    tag_id: str
    nome: str
    tenant_id: str

@app.get("/api/admin/tenants", tags=["Admin"])
def admin_get_tenants(_: str = Depends(require_admin)):
    """lista todos os tenants"""
    try:
        with get_db_connection() as conn:
            clientes = conn.execute("SELECT id, nome, password FROM clientes").fetchall()
            return [{"id": c["id"], "nome": c["nome"], "password": c["password"] or ""} for c in clientes]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao obter clientes: {exc}")

@app.get("/api/mapas", tags=["General"])
def obter_mapas_utilizador(tenant_id: str = Depends(aplicar_rate_limit)):
    """devolve mapas associados ao utilizador autenticado"""
    try:
        with get_db_connection() as conn:
            mapas = conn.execute("SELECT id, nome, limite_x, limite_y, ficheiro_img FROM mapas WHERE cliente_id = ?", (tenant_id,)).fetchall()
            return [
                {
                    "id": m["id"],
                    "nome": m["nome"],
                    "limite_x": m["limite_x"],
                    "limite_y": m["limite_y"],
                    "path": m["ficheiro_img"]
                } for m in mapas
            ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao obter mapas: {exc}")

@app.get("/api/admin/config/{tenant_id}", tags=["Admin"])
def admin_get_config(tenant_id: str, payload: dict = Depends(obter_payload_token)):
    _verificar_acesso_tenant(tenant_id, payload)
    """obtem configuracoes de mapas, tags e utilizadores de um tenant."""
    try:
        with get_db_connection() as conn:
            users = conn.execute(
                "SELECT username FROM users WHERE cliente_id = ?", (tenant_id,)
            ).fetchall()
            mapas = conn.execute(
                "SELECT id, nome, limite_x, limite_y, ficheiro_img FROM mapas WHERE cliente_id = ?",
                (tenant_id,)
            ).fetchall()
            tags = conn.execute(
                "SELECT id_fisico, nome FROM tags WHERE cliente_id = ?", (tenant_id,)
            ).fetchall()
            return {
                "tenant_id": tenant_id,
                "users": [u["username"] for u in users],
                "mapas": [
                    {
                        "id": m["id"],
                        "nome": m["nome"],
                        "limite_x": m["limite_x"],
                        "limite_y": m["limite_y"],
                        "path": m["ficheiro_img"]
                    } for m in mapas
                ],
                "tags": [
                    {"tag_id": t["id_fisico"], "friendly_name": t["nome"]} for t in tags
                ]
            }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao obter config: {exc}")

@app.post("/api/admin/mapas", tags=["Admin"])
def admin_create_mapa(
    data: MapaCreate,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
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
            log_audit_event, admin_tenant, data.tenant_id,
            "map_created", f"Mapa '{data.nome}' criado (Dimensões: {data.limite_x}x{data.limite_y} cm, Imagem: {data.ficheiro_img or 'Nenhuma'})",
        )
        return {"sucesso": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao criar mapa: {exc}")

@app.put("/api/admin/mapas/{map_id}", tags=["Admin"])
def admin_update_mapa(
    map_id: int,
    data: MapaUpdate,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT cliente_id, nome, limite_x, limite_y, ficheiro_img FROM mapas WHERE id = ?", (map_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Mapa não encontrado.")
            _verificar_acesso_tenant(row["cliente_id"], payload)
            conn.execute(
                "UPDATE mapas SET nome = ?, limite_x = ?, limite_y = ?, ficheiro_img = ? WHERE id = ?",
                (data.nome, data.limite_x, data.limite_y, data.ficheiro_img, map_id)
            )
            conn.commit()
            
        old_state = f"[{row['nome']} | {row['limite_x']}x{row['limite_y']} | {row['ficheiro_img'] or 'Sem IMG'}]"
        new_state = f"[{data.nome} | {data.limite_x}x{data.limite_y} | {data.ficheiro_img or 'Sem IMG'}]"
        
        background_tasks.add_task(
            log_audit_event, admin_tenant, row["cliente_id"],
            "map_updated", f"Mapa ID:{map_id} atualizado. ANTES: {old_state} -> DEPOIS: {new_state}",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao atualizar mapa: {exc}")

@app.delete("/api/admin/mapas/{map_id}", tags=["Admin"])
def admin_delete_mapa(
    map_id: int,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT cliente_id, nome FROM mapas WHERE id = ?", (map_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Mapa não encontrado.")
            _verificar_acesso_tenant(row["cliente_id"], payload)
            conn.execute("DELETE FROM ancoras WHERE mapa_id = ?", (map_id,))
            conn.execute("DELETE FROM mapas WHERE id = ?", (map_id,))
            conn.commit()
        background_tasks.add_task(
            log_audit_event, admin_tenant, row["cliente_id"],
            "map_deleted", f"Mapa '{row['nome']}' (ID: {map_id}) e todas as suas âncoras apagados.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao apagar mapa: {exc}")

@app.post("/api/admin/tags/aliases", tags=["Admin"])
def admin_update_aliases(
    data: TagAliasesUpdate,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    """atualiza os aliases das tags"""
    if payload.get("role") not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Acesso negado.")
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            for tag in data.tags:
                if payload.get("role") == "admin":
                    conn.execute(
                        "UPDATE tags SET nome = ? WHERE id_fisico = ? AND cliente_id = ?",
                        (tag.friendly_name, tag.tag_id, admin_tenant),
                    )
                else:
                    conn.execute(
                        "UPDATE tags SET nome = ? WHERE id_fisico = ?",
                        (tag.friendly_name, tag.tag_id),
                    )
            conn.commit()
        aliases_log = ", ".join([f"[{t.tag_id} -> '{t.friendly_name}']" for t in data.tags])
        background_tasks.add_task(
            log_audit_event, admin_tenant, admin_tenant,
            "tag_aliases_updated", f"Nomes de {len(data.tags)} tags atualizados: {aliases_log}",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro ao atualizar tags: {exc}")

# CRUD endpoints

@app.post("/api/admin/tenants", tags=["Admin"])
def admin_create_tenant(data: TenantCreate, background_tasks: BackgroundTasks, admin_tenant: str = Depends(require_admin)):
    try:
        with get_db_connection() as conn:
            clean_name = re.sub(r'[^a-z0-9]', '_', data.nome.lower())
            clean_name = re.sub(r'_+', '_', clean_name).strip('_')[:10]
            suffix = uuid.uuid4().hex[:6]
            novo_id = f"{clean_name}_{suffix}" if clean_name else f"tenant_{suffix}"
            conn.execute(
                "INSERT INTO clientes (id, nome, password) VALUES (?, ?, ?)",
                (novo_id, data.nome, data.password or None),
            )
            conn.commit()
            
        background_tasks.add_task(
            log_audit_event, admin_tenant, novo_id,
            "tenant_created", f"Cliente '{data.nome}' criado com sucesso (ID: {novo_id}).",
        )
        return {"sucesso": True, "id": novo_id}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Erro interno ao gerar ID.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")

@app.put("/api/admin/tenants/{tenant_id}", tags=["Admin"])
def admin_update_tenant(tenant_id: str, data: TenantUpdate, background_tasks: BackgroundTasks, admin_tenant: str = Depends(require_admin)):
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT nome FROM clientes WHERE id = ?", (tenant_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Cliente não encontrado.")
            
            if data.password is not None:
                conn.execute("UPDATE clientes SET nome = ?, password = ? WHERE id = ?",
                             (data.nome, data.password or None, tenant_id))
            else:
                conn.execute("UPDATE clientes SET nome = ? WHERE id = ?", (data.nome, tenant_id))
                
            conn.commit()
            
        pass_mudou = "Sim" if data.password else "Não"
        background_tasks.add_task(
            log_audit_event, admin_tenant, tenant_id,
            "tenant_updated", f"Cliente ID: {tenant_id} atualizado. Nome alterado de '{row['nome']}' para '{data.nome}'. Password Alterada: {pass_mudou}.",
        )
        return {"sucesso": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")

@app.delete("/api/admin/tenants/{tenant_id}", tags=["Admin"])
def admin_delete_tenant(tenant_id: str, background_tasks: BackgroundTasks, admin_tenant: str = Depends(require_admin)):
    if tenant_id == ADMIN_TENANT_ID:
        raise HTTPException(status_code=400, detail="Não pode apagar o utilizador administrador do sistema.")
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT nome FROM clientes WHERE id = ?", (tenant_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Cliente não encontrado.")
            
            conn.execute("DELETE FROM tags WHERE cliente_id = ?", (tenant_id,))
            conn.execute("DELETE FROM users WHERE cliente_id = ?", (tenant_id,))
            mapas = conn.execute("SELECT id FROM mapas WHERE cliente_id = ?", (tenant_id,)).fetchall()
            for mapa in mapas:
                conn.execute("DELETE FROM ancoras WHERE mapa_id = ?", (mapa["id"],))
            conn.execute("DELETE FROM mapas WHERE cliente_id = ?", (tenant_id,))
            conn.execute("DELETE FROM clientes WHERE id = ?", (tenant_id,))
            conn.commit()
            global UTILIZADORES
            UTILIZADORES = carregar_utilizadores_db()
            
        background_tasks.add_task(
            log_audit_event, admin_tenant, tenant_id,
            "tenant_deleted", f"Cliente '{row['nome']}' (ID: {tenant_id}) apagado e todos os seus dados eliminados em cascata (Utilizadores, Mapas, Tags, Âncoras).",
        )
        return {"sucesso": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")

@app.post("/api/admin/users", tags=["Admin"])
def admin_create_user(
    data: UserCreate,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    _verificar_acesso_tenant(data.tenant_id, payload)
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            existing_user = conn.execute(
                "SELECT u.username, c.nome as cliente_nome FROM users u JOIN clientes c ON u.cliente_id = c.id WHERE u.username = ?",
                (data.username,)
            ).fetchone()
            if existing_user:
                raise HTTPException(status_code=400, detail=f"O username '{data.username}' já está em uso no cliente '{existing_user['cliente_nome']}'.")
            conn.execute(
                "INSERT INTO users (username, password, cliente_id) VALUES (?, ?, ?)",
                (data.username, data.password, data.tenant_id)
            )
            conn.commit()
            global UTILIZADORES
            UTILIZADORES = carregar_utilizadores_db()
        background_tasks.add_task(
            log_audit_event, admin_tenant, data.tenant_id,
            "user_created", f"Utilizador '{data.username}' criado para este cliente.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="O username já existe.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")

@app.put("/api/admin/users/{username}", tags=["Admin"])
def admin_update_user(username: str, data: UserUpdate, background_tasks: BackgroundTasks, payload: dict = Depends(obter_payload_token)):
    if username == ADMIN_USERNAME and data.new_username and data.new_username != ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="Não pode alterar o username da conta admin principal.")
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            db_user = conn.execute("SELECT password, cliente_id FROM users WHERE username = ?", (username,)).fetchone()
            if not db_user:
                raise HTTPException(status_code=404, detail="Utilizador não encontrado.")
            _verificar_acesso_tenant(db_user["cliente_id"], payload)
            if data.new_username and data.new_username != username:
                existing_user = conn.execute(
                    "SELECT u.username, c.nome as cliente_nome FROM users u JOIN clientes c ON u.cliente_id = c.id WHERE u.username = ?",
                    (data.new_username,)
                ).fetchone()
                if existing_user:
                    raise HTTPException(status_code=400, detail=f"O novo username '{data.new_username}' já está a ser utilizado.")
            novo_user = data.new_username if data.new_username else username
            nova_pass = data.password if data.password else db_user["password"]
            pass_mudou = "Sim" if data.password else "Não"
            conn.execute("UPDATE users SET username = ?, password = ? WHERE username = ?", (novo_user, nova_pass, username))
            conn.commit()
            global UTILIZADORES
            UTILIZADORES = carregar_utilizadores_db()
            
        background_tasks.add_task(
            log_audit_event, admin_tenant, db_user["cliente_id"],
            "user_updated", f"Utilizador '{username}' atualizado. Novo Username: '{novo_user}', Password Alterada: {pass_mudou}.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="O novo username já está em uso.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")

@app.delete("/api/admin/users/{username}", tags=["Admin"])
def admin_delete_user(
    username: str,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    if username == ADMIN_USERNAME:
        raise HTTPException(status_code=400, detail="Não pode apagar a conta admin.")
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT cliente_id FROM users WHERE username = ?", (username,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Utilizador não encontrado.")
            _verificar_acesso_tenant(row["cliente_id"], payload)
            conn.execute("DELETE FROM users WHERE username = ?", (username,))
            conn.commit()
            global UTILIZADORES
            UTILIZADORES = carregar_utilizadores_db()
        background_tasks.add_task(
            log_audit_event, admin_tenant, row["cliente_id"],
            "user_deleted", f"Utilizador '{username}' apagado permanentemente.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")

@app.post("/api/admin/tags", tags=["Admin"])
def admin_create_tag(
    data: TagCreate,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    _verificar_acesso_tenant(data.tenant_id, payload)
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO tags (id_fisico, nome, cliente_id) VALUES (?, ?, ?)",
                (data.tag_id, data.nome, data.tenant_id)
            )
            conn.commit()
        background_tasks.add_task(
            log_audit_event, admin_tenant, data.tenant_id,
            "tag_created", f"Nova Tag monitorizada: ID Físico '{data.tag_id}', Nome Amigável '{data.nome}'.",
        )
        return {"sucesso": True}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Tag já existe.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")

@app.delete("/api/admin/tags/{tag_id}", tags=["Admin"])
def admin_delete_tag(
    tag_id: str,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    admin_tenant = payload["tenant_id"]
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT cliente_id FROM tags WHERE id_fisico = ?", (tag_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tag não encontrada.")
            _verificar_acesso_tenant(row["cliente_id"], payload)
            conn.execute("DELETE FROM tags WHERE id_fisico = ?", (tag_id,))
            conn.commit()
        background_tasks.add_task(
            log_audit_event, admin_tenant, row["cliente_id"],
            "tag_deleted", f"Tag '{tag_id}' apagada permanentemente.",
        )
        return {"sucesso": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"erro: {exc}")

# ---------------------------------------------------------------------------
# logs de auditoria (InfluxDB measurement: system_access_log)
# ---------------------------------------------------------------------------

_AUDIT_LOG_INFLUX_LIMIT = 10_000


def _parse_query_ts(val: str) -> datetime:
    """converte parâmetro ISO8601 para datetime UTC."""
    normalizado = val.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalizado)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _flux_time_literal(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolver_intervalo_audit(
    ts_inicio: Optional[str],
    ts_fim: Optional[str],
) -> tuple[str, str]:
    """devolve (start, stop) para range() do Flux."""
    if not ts_inicio and not ts_fim:
        # sem filtro temporal: máximo histórico retido no bucket Influx
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


def _carregar_system_access_log(
    start: str,
    stop: str,
    tenant_id: Optional[str] = None,
) -> list[dict]:
    """lê eventos da measurement system_access_log (mesma fonte do histórico de sessões)."""
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
        |> limit(n: {_AUDIT_LOG_INFLUX_LIMIT})
    """
    resultados = get_influx_client().query_api().query(org=INFLUX_ORG, query=query)
    eventos: list[dict] = []
    for tabela in resultados:
        for registro in tabela.records:
            ts = registro.values.get("_time")
            eventos.append({
                "timestamp": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
                "tenant_id": registro.values.get("tenant_id") or "",
                "username": registro.values.get("user_id") or "",
                "acao": registro.values.get("action") or "",
                "detalhes": registro.values.get("details") or "",
            })
    return eventos


@app.get("/admin/audit-log", tags=["Admin"])
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
    """
    Log global de ações de utilizadores (system_access_log / InfluxDB).
    Filtros combinados em AND; resposta vazia em caso de erro — nunca HTTP 500.
    """
    page_size = min(max(page_size, 1), 2000)
    try:
        if tenant_id and not validar_tenant_id(tenant_id):
            return {
                "total": 0,
                "page": page,
                "page_size": page_size,
                "resultados": [],
            }

        try:
            start, stop = _resolver_intervalo_audit(ts_inicio, ts_fim)
        except (ValueError, TypeError):
            return {
                "total": 0,
                "page": page,
                "page_size": page_size,
                "resultados": [],
            }

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

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "resultados": pagina,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha ao consultar audit-log: %s", exc)
        return {
            "total": 0,
            "page": page,
            "page_size": page_size,
            "resultados": [],
        }


@app.get("/api/admin/tenants/{tenant_id}/sessions", tags=["Admin"])
def admin_get_tenant_sessions(
    tenant_id: str,
    start: str = Query("-30d", description="Início relativo (ex: -7d) ou ISO 8601"),
    stop: str = Query("now()", description="Fim relativo ou ISO 8601"),
    action: Optional[str] = Query(None, description="Filtro opcional por tipo de ação"),
    payload: dict = Depends(obter_payload_token),
):
    """logs de auditoria do sistema para um cliente específico — visíveis pelo administrador."""
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
        |> limit(n: 500)
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


# perfil do cliente (conta admin da empresa — tabela clientes)

def _require_tenant_admin(payload: dict) -> str:
    if payload.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Apenas o administrador da empresa pode alterar estes dados.",
        )
    return payload["tenant_id"]


def _cliente_row_ou_404(conn: sqlite3.Connection, tenant_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT id, nome, password, logo_url FROM clientes WHERE id = ?", (tenant_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Cliente não encontrado.")
    return row


def _extensao_avatar_por_conteudo(conteudo: bytes, filename: str = "") -> str:
    """detecta tipo real pela assinatura do ficheiro (fiável no Windows)."""
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

    raise HTTPException(
        status_code=400,
        detail="Formato não suportado. Envie PNG, JPEG ou WebP.",
    )


def _remover_ficheiros_avatar(tenant_id: str) -> None:
    AVATARS_FS_DIR.mkdir(parents=True, exist_ok=True)
    for ficheiro in AVATARS_FS_DIR.glob(f"{tenant_id}.*"):
        if ficheiro.is_file():
            ficheiro.unlink(missing_ok=True)


def _logo_url_canonica(tenant_id: str, ext: str) -> str:
    return f"{AVATARS_URL_PREFIX}{tenant_id}{ext}"


@app.get("/api/tenant/branding", tags=["Tenant"])
def obter_tenant_branding(payload: dict = Depends(obter_payload_token)):
    """nome e avatar do tenant do utilizador autenticado (user ou admin)."""
    tenant_id = payload["tenant_id"]
    with get_db_connection() as conn:
        row = _cliente_row_ou_404(conn, tenant_id)
    return {
        "tenant_id": row["id"],
        "nome": row["nome"],
        "logo_url": row["logo_url"],
    }


class TenantProfileUpdate(BaseModel):
    nome: Optional[str] = None
    new_password: Optional[str] = None
    current_password: str


@app.put("/api/tenant/profile", tags=["Tenant"])
def atualizar_tenant_profile(
    data: TenantProfileUpdate,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    """admin da empresa: altera nome de exibição e password de login (tabela clientes)."""
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
            raise HTTPException(status_code=400, detail="O nome do cliente não pode estar vazio.")

        nova_pass = data.new_password if data.new_password else row["password"]
        conn.execute(
            "UPDATE clientes SET nome = ?, password = ? WHERE id = ?",
            (novo_nome, nova_pass, tenant_id),
        )
        conn.commit()

    pass_mudou = "Sim" if data.new_password else "Não"
    background_tasks.add_task(
        log_audit_event,
        subject,
        tenant_id,
        "tenant_profile_updated",
        f"Nome: '{novo_nome}', Password alterada: {pass_mudou}.",
    )
    return {
        "sucesso": True,
        "tenant_id": tenant_id,
        "nome": novo_nome,
        "nome_alterado": novo_nome != row["nome"],
    }


@app.post("/api/tenant/profile/avatar", tags=["Tenant"])
async def upload_tenant_avatar(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    payload: dict = Depends(obter_payload_token),
):
    """admin: upload de avatar — grava como {tenant_id}.<ext> e actualiza logo_url."""
    tenant_id = _require_tenant_admin(payload)
    subject = payload.get("sub", "")

    conteudo = await file.read()
    if len(conteudo) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Imagem demasiado grande (máximo 2 MB).")
    if len(conteudo) < 100:
        raise HTTPException(status_code=400, detail="Ficheiro de imagem inválido ou vazio.")

    ext = _extensao_avatar_por_conteudo(conteudo, file.filename or "")
    if ext not in ALLOWED_AVATAR_EXT:
        raise HTTPException(status_code=400, detail="Extensão de ficheiro não permitida.")

    AVATARS_FS_DIR.mkdir(parents=True, exist_ok=True)
    _remover_ficheiros_avatar(tenant_id)
    destino = AVATARS_FS_DIR / f"{tenant_id}{ext}"
    destino.write_bytes(conteudo)

    logo_url = _logo_url_canonica(tenant_id, ext)
    with get_db_connection() as conn:
        _cliente_row_ou_404(conn, tenant_id)
        conn.execute("UPDATE clientes SET logo_url = ? WHERE id = ?", (logo_url, tenant_id))
        conn.commit()

    background_tasks.add_task(
        log_audit_event,
        subject,
        tenant_id,
        "tenant_avatar_uploaded",
        f"Avatar actualizado: {logo_url}",
    )
    return {"sucesso": True, "logo_url": logo_url}


@app.delete("/api/tenant/profile/avatar", tags=["Tenant"])
def remover_tenant_avatar(
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    """admin: remove avatar do disco e limpa logo_url."""
    tenant_id = _require_tenant_admin(payload)
    subject = payload.get("sub", "")

    _remover_ficheiros_avatar(tenant_id)
    with get_db_connection() as conn:
        _cliente_row_ou_404(conn, tenant_id)
        conn.execute("UPDATE clientes SET logo_url = NULL WHERE id = ?", (tenant_id,))
        conn.commit()

    background_tasks.add_task(
        log_audit_event,
        subject,
        tenant_id,
        "tenant_avatar_removed",
        "Avatar da empresa removido.",
    )
    return {"sucesso": True, "logo_url": None}


# auto-gestao de credenciais (qualquer utilizador autenticado)

class SelfCredentialsUpdate(BaseModel):
    new_username: Optional[str] = None
    new_password: Optional[str] = None
    current_password: str


@app.put("/api/user/credentials", tags=["User"])
def update_self_credentials(
    data: SelfCredentialsUpdate,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(obter_payload_token),
):
    """permite ao utilizador autenticado alterar o seu proprio username e/ou password"""
    if payload.get("role") == "admin":
        raise HTTPException(
            status_code=403,
            detail="Conta ADMIN não tem credenciais na tabela de utilizadores.",
        )
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

        conn.execute(
            "UPDATE users SET username = ?, password = ? WHERE username = ?",
            (new_name, new_password, current_username)
        )
        conn.commit()

        global UTILIZADORES
        UTILIZADORES = carregar_utilizadores_db()

        pass_mudou = "Sim" if data.new_password else "Não"
        background_tasks.add_task(
            log_audit_event, current_username, user["cliente_id"],
            "credentials_updated", f"O utilizador atualizou os seus dados. Novo Username: '{new_name}', Password Alterada: {pass_mudou}."
        )

        username_changed = bool(data.new_username and data.new_username != current_username)
        return {"sucesso": True, "username_changed": username_changed}