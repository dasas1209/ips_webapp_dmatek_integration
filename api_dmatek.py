"""
api_dmatek.py
api rest do sistema metric4 rtls
"""
import math
import re
import sqlite3
import logging
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from influxdb_client import InfluxDBClient  # type: ignore
from jose import JWTError, jwt  # type: ignore

from config import (
    ALGORITHM,
    ALLOWED_ORIGINS,
    INFLUX_BUCKET,
    INFLUX_ORG,
    INFLUX_TOKEN,
    INFLUX_URL,
    JANELA_KPI_HORAS,
    LIMITE_DIAS_HISTORICO,
    LIMITE_X_CM,
    LIMITE_Y_CM,
    LIMIAR_MOVIMENTO_CM,
    SECRET_KEY,
    TOKEN_EXPIRY_HOURS,
)
from shared import get_db_connection

# configuracao da aplicacao fastapi

app = FastAPI(
    title="Portal de Dados RTLS — Metric4",
    description="API de Gestão Multi-Tenant para posições em tempo real.",
    version="2.0.0",
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


class TenantRateLimiter:
    """throttling em memória por tenant para reduzir risco de noisy neighbor"""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._state: dict[str, dict[str, float | int]] = {}
        self._lock = Lock()

    def allow(self, tenant_id: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tenant_state = self._state.get(tenant_id)
            if tenant_state is None or (now - float(tenant_state["window_start"])) >= self.window_seconds:
                self._state[tenant_id] = {"window_start": now, "count": 1}
                return True

            tenant_state["count"] = int(tenant_state["count"]) + 1
            return int(tenant_state["count"]) <= self.max_requests


tenant_rate_limiter = TenantRateLimiter(max_requests=120, window_seconds=60)

# configuracao de seguranca jwt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


def criar_token_jwt(dados: dict) -> str:
    """gera jwt assinado"""
    payload = dados.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)  # type: ignore


def verificar_token(token: str = Depends(oauth2_scheme)) -> str:
    """valida jwt e devolve tenant id"""
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
def login(credenciais: OAuth2PasswordRequestForm = Depends()):
    """autentica utilizador e devolve jwt"""
    utilizador = UTILIZADORES.get(credenciais.username)
    if not utilizador:
        raise HTTPException(status_code=401, detail="Utilizador não existe.")
    if utilizador["password"] != credenciais.password:
        raise HTTPException(status_code=401, detail="Password incorreta.")

    tenant_id = utilizador["tenant_id"]
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
        with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
            tabelas = client.query_api().query(query)

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
            "cliente":              tenant_id,
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
        with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
            tabelas = client.query_api().query(query)

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
            "cliente":              tenant_id,
            "total_tags_detetadas": len(posicoes),
            "dados":                posicoes,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao consultar histórico: {exc}")


# rotas de kpis

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

    frota = {"distancia_total_cm": 0.0, "leituras_em_movimento": 0, "leituras_totais": 0}
    tags_processadas: dict[str, dict] = {}

    try:
        with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
            resultado = client.query_api().query(org=INFLUX_ORG, query=query)

        for table in resultado:
            for record in table.records:
                tag_id   = record.values.get("tag_id")
                x_atual  = record.values.get("coord_x")
                y_atual  = record.values.get("coord_y")
                bateria  = record.values.get("bateria")

                if tag_id is None or x_atual is None or y_atual is None:
                    continue

                frota["leituras_totais"] += 1

                if tag_id not in tags_processadas:
                    tags_processadas[tag_id] = {
                        "ultimo_x": None, "ultimo_y": None,
                        "bateria": 0, "distancia_cm": 0.0,
                        "leituras_totais": 0, "leituras_em_movimento": 0,
                    }

                tag = tags_processadas[tag_id]
                tag["leituras_totais"] += 1
                if bateria is not None:
                    tag["bateria"] = bateria

                if tag["ultimo_x"] is not None:
                    dist = math.sqrt(
                        (x_atual - tag["ultimo_x"]) ** 2 +
                        (y_atual - tag["ultimo_y"]) ** 2
                    )
                    frota["distancia_total_cm"] += dist
                    tag["distancia_cm"]         += dist
                    if dist > LIMIAR_MOVIMENTO_CM:
                        frota["leituras_em_movimento"]  += 1
                        tag["leituras_em_movimento"]    += 1

                tag["ultimo_x"] = x_atual
                tag["ultimo_y"] = y_atual

        # agregados finais
        distancia_m    = round(frota["distancia_total_cm"] / 100, 2)
        taxa_utilizacao = 0.0
        if frota["leituras_totais"] > 0:
            taxa_utilizacao = round(
                (frota["leituras_em_movimento"] / frota["leituras_totais"]) * 100, 1
            )

        baterias = [d["bateria"] for d in tags_processadas.values() if d["bateria"] > 0]
        bateria_media = round(sum(baterias) / len(baterias), 1) if baterias else 0.0

        grafico_distancias = {t: round(d["distancia_cm"] / 100, 2) for t, d in tags_processadas.items()}
        grafico_utilizacao = {
            t: round((d["leituras_em_movimento"] / d["leituras_totais"]) * 100, 1)
            if d["leituras_totais"] > 0 else 0.0
            for t, d in tags_processadas.items()
        }
        grafico_bateria = {t: round(d["bateria"], 1) for t, d in tags_processadas.items()}

        # total de tags registadas na bd (independente da actividade influx)
        try:
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM tags WHERE cliente_id = ?",
                    (tenant_id,),
                ).fetchone()
            total_assets_bd = row["n"] if row else 0
        except Exception:
            total_assets_bd = len(tags_processadas)

        return {
            "sucesso":    True,
            "tenant_id":  tenant_id,
            "kpis": {
                "distancia_percorrida_metros": distancia_m,
                "taxa_utilizacao_perc":        taxa_utilizacao,
                "bateria_media_frota_perc":    bateria_media,
                "tags_ativas_turno":           len(tags_processadas),
                "total_assets":                total_assets_bd,
            },
            "grafico_distancias": grafico_distancias,
            "grafico_utilizacao": grafico_utilizacao,
            "grafico_bateria":    grafico_bateria,
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


def _obter_limites_mapa_cliente(cliente_id: str) -> tuple[float, float]:
    """devolve (limite_x, limite_y) do mapa do cliente a partir da bd"""
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT limite_x, limite_y FROM mapas WHERE cliente_id = ? LIMIT 1",
                (cliente_id,),
            ).fetchone()
        if row:
            return float(row["limite_x"]), float(row["limite_y"])
    except sqlite3.Error as exc:
        logger.warning("nao foi possivel obter limites do mapa para %s: %s", cliente_id, exc)
    # fallback defensivo para clientes sem mapa registado
    return LIMITE_X_CM, LIMITE_Y_CM


def _eventos_auditoria_influx_para_incidentes(
    tabelas,
    limite_x: float,
    limite_y: float,
) -> list[dict]:
    """converte resultados flux da measurement evento_auditoria para o formato da lista incidentes."""
    eventos: list[dict] = []
    for table in tabelas:
        for record in table.records:
            tag_id = record.values.get("tag_id")
            tipo = record.values.get("tipo")
            ts = record.values.get("_time")
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
    cliente_id: str = Depends(aplicar_rate_limit),
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
        |> filter(fn: (r) => r["tenant_id"] == "{cliente_id}")
        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        |> group(columns: ["tag_id"])
        |> sort(columns: ["_time"])
    """

    query_eventos_auditoria = f"""
        from(bucket: "{INFLUX_BUCKET}")
        |> range(start: {inicio_safe}, stop: {fim_safe})
        |> filter(fn: (r) => r["_measurement"] == "evento_auditoria")
        |> filter(fn: (r) => r["tenant_id"] == "{cliente_id}")
        |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        |> sort(columns: ["_time"])
    """

    try:
        limite_x, limite_y = _obter_limites_mapa_cliente(cliente_id)

        with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
            qa = client.query_api()
            resultado = qa.query(org=INFLUX_ORG, query=query_trajetoria)
            resultado_eventos = qa.query(org=INFLUX_ORG, query=query_eventos_auditoria)

        esparguete_pontos: list[dict] = []
        incidentes:        list[dict] = []
        tags_processadas:  dict[str, dict] = {}

        for table in resultado:
            for record in table.records:
                tag_id  = record.values.get("tag_id")
                x_cm    = record.values.get("coord_x")
                y_cm    = record.values.get("coord_y")
                bateria = record.values.get("bateria")
                status  = record.values.get("status")
                ts      = record.values.get("_time")

                if tag_id is None or x_cm is None or y_cm is None:
                    continue

                x_norm = round(x_cm / LIMITE_X_CM, 5)
                y_norm = round(y_cm / LIMITE_Y_CM, 5)
                ts_iso = ts.isoformat() if ts else None

                esparguete_pontos.append({"tag_id": tag_id, "x": x_norm, "y": y_norm, "t": ts_iso})

                if status is not None and status != "Normal":
                    incidentes.append({
                        "tag_id":    tag_id,
                        "timestamp": ts_iso,
                        "tipo":      status,
                        "x":         x_norm,
                        "y":         y_norm,
                    })

                if tag_id not in tags_processadas:
                    tags_processadas[tag_id] = {
                        "ultimo_x": None, "ultimo_y": None, "ultimo_ts": None,
                        "distancia_cm": 0.0,
                        "bateria_min":   bateria if bateria is not None else 100.0,
                        "bateria_ultima": bateria if bateria is not None else 0.0,
                        "leituras_totais": 0, "leituras_em_movimento": 0,
                        "tempo_ocioso_seg": 0.0,
                    }

                kpi = tags_processadas[tag_id]
                kpi["leituras_totais"] += 1

                if bateria is not None:
                    kpi["bateria_ultima"] = bateria
                    if bateria < kpi["bateria_min"]:
                        kpi["bateria_min"] = bateria

                if kpi["ultimo_x"] is not None:
                    dist = math.sqrt(
                        (x_cm - kpi["ultimo_x"]) ** 2 +
                        (y_cm - kpi["ultimo_y"]) ** 2
                    )
                    kpi["distancia_cm"] += dist
                    if dist > LIMIAR_MOVIMENTO_CM:
                        kpi["leituras_em_movimento"] += 1
                    elif kpi["ultimo_ts"] is not None and ts is not None:
                        kpi["tempo_ocioso_seg"] += max((ts - kpi["ultimo_ts"]).total_seconds(), 0)

                kpi["ultimo_x"]  = x_cm
                kpi["ultimo_y"]  = y_cm
                kpi["ultimo_ts"] = ts

        # conta alertas por tag
        alertas_por_tag = Counter(inc["tag_id"] for inc in incidentes)

        kpis_por_tag = []
        distancia_frota_m    = 0.0
        baterias_para_media: list[float] = []

        for tag_id, kpi in tags_processadas.items():
            distancia_m = round(kpi["distancia_cm"] / 100, 2)
            distancia_frota_m += distancia_m

            oee_perc = 0.0
            if kpi["leituras_totais"] > 0:
                oee_perc = round(
                    (kpi["leituras_em_movimento"] / kpi["leituras_totais"]) * 100, 1
                )

            bateria_min = round(kpi["bateria_min"], 1) if kpi["bateria_min"] < 100.0 else 0.0
            if kpi["bateria_ultima"] > 0:
                baterias_para_media.append(kpi["bateria_ultima"])

            kpis_por_tag.append({
                "tag_id":           tag_id,
                "distancia_m":      distancia_m,
                "oee_perc":         oee_perc,
                "bateria_min_perc": bateria_min,
                "tempo_ocioso_min": round(kpi["tempo_ocioso_seg"] / 60, 1),
                "num_alertas":      alertas_por_tag[tag_id],
            })

        kpis_por_tag.sort(key=lambda t: t["tag_id"])

        try:
            eventos_audit = _eventos_auditoria_influx_para_incidentes(
                resultado_eventos, limite_x, limite_y
            )
            incidentes.extend(eventos_audit)
        except Exception:
            logger.exception("falha ao agregar eventos evento_auditoria do influx")

        incidentes.sort(key=lambda x: x.get("timestamp", ""))

        bateria_media_frota = 0.0
        if baterias_para_media:
            bateria_media_frota = round(sum(baterias_para_media) / len(baterias_para_media), 1)

        return {
            "sucesso":  True,
            "cliente":  cliente_id,
            "periodo":  {"inicio": inicio, "fim": fim},
            "kpis_frota": {
                "distancia_total_m":  round(distancia_frota_m, 2),
                "bateria_media_perc": bateria_media_frota,
                "total_incidentes":   len(incidentes),
                "tags_ativas":        len(tags_processadas),
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