"""
app/services/database.py
utilitarios de acesso a base de dados sqlite e validacao de tenant
"""

import logging
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "metric4rtls_system.db"

logger = logging.getLogger("metric4.api")

# allowlist apenas alfanumerico underscore e hifen max 64 chars
_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def get_db_connection() -> sqlite3.Connection:
    """devolve ligacao sqlite com row_factory e fks activos — ativa wal se possivel"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass  # db em delete mode — sera migrado para wal na proxima abertura exclusiva
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def validar_tenant_id(tenant_id: str) -> bool:
    """valida tenant_id contra allowlist de caracteres — previne flux injection"""
    return bool(_TENANT_ID_RE.match(tenant_id or ""))


def carregar_matriz_clientes() -> dict[str, str]:
    """le a tabela tags e devolve mapeamento {id_fisico: cliente_id}"""
    matriz: dict[str, str] = {}
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT id_fisico, cliente_id FROM tags").fetchall()
        for row in rows:
            matriz[row["id_fisico"]] = row["cliente_id"]
        logger.info("matriz carregada da bd: %s tag(s) mapeada(s)", len(matriz))
    except sqlite3.Error as exc:
        logger.error("falha ao ler matriz de clientes da bd: %s", exc)
    return matriz


def obter_limites_mapa(cliente_id: str) -> tuple[float, float]:
    """devolve (limite_x, limite_y) do primeiro mapa associado ao cliente"""
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

    # fallback defensivo: valores do config original
    from config import LIMITE_X_CM, LIMITE_Y_CM  # noqa: PLC0415
    return LIMITE_X_CM, LIMITE_Y_CM
