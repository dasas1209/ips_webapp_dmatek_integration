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
from threading import Lock
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
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
)
from services.database import (
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
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")

# logging de seguranca (sem coordenadas para minimizar exposição de localização)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("metric4.api")


# serving de paginas html

@app.get("/", include_in_schema=False)
@app.get("/app", include_in_schema=False)
async def serve_index():
    return FileResponse("frontend/index.html")


@app.get("/relatorio.html", include_in_schema=False)
async def serve_relatorio():
    return FileResponse("frontend/relatorio.html")


@app.get("/auditoria.html", include_in_schema=False)
async def serve_auditoria():
    return FileResponse("frontend/auditoria.html")


# carregamento de utilizadores da base de dados

def carregar_utilizadores_db() -> dict[str, dict]:
    """carrega utilizadores da bd sqlite — substitui o csv placeholder"""
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
            f"Falha ao ler utilizadores da BD: {exc}. "
            "Garante que database_setup.py foi executado."
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


def verificar_token(token: str = Depends(oauth2_scheme)) -> str:
    """valida jwt e devolve tenant_id"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])  # type: ignore
        tenant_id: Optional[str] = payload.get("tenant_id")
        if tenant_id is None:
            raise HTTPException(status_code=401, detail="Token sem identificação de cliente.")
        return tenant_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Acesso negado: token inválido ou expirado.")


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
def login(credenciais: OAuth2PasswordRequestForm = Depends(), request: Request = None):
    """autentica utilizador e devolve jwt"""
    # throttling por username — previne brute force
    if not login_rate_limiter.allow(credenciais.username):
        logger.warning("Rate limit de login excedido para username=%s", credenciais.username)
        raise HTTPException(status_code=429, detail="Demasiadas tentativas de login. Aguarde 1 minuto.")

    utilizador = UTILIZADORES.get(credenciais.username)
    if not utilizador:
        raise HTTPException(status_code=401, detail="Utilizador não existe.")
    if utilizador["password"] != credenciais.password:
        raise HTTPException(status_code=401, detail="Password incorreta.")

    tenant_id = utilizador["tenant_id"]

    # valida tenant_id antes de assinar o jwt — previne flux injection
    if not validar_tenant_id(tenant_id):
        logger.error("tenant_id invalido detectado no login: user=%s", credenciais.username)
        raise HTTPException(status_code=400, detail="Identificador de cliente inválido.")

    logger.info("Login bem-sucedido para user=%s tenant_id=%s", credenciais.username, tenant_id)
    token = criar_token_jwt({"sub": credenciais.username, "tenant_id": tenant_id})
    return {
        "access_token": token,
        "token_type":   "bearer",
        "tenant_id":    tenant_id,
        "mensagem":     f"Bem-vindo, {credenciais.username}.",
    }


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

        return {
            "tenant_id":            tenant_id,
            "total_tags_detetadas": len(posicoes),
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