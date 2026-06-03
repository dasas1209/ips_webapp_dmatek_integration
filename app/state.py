"""
app/state.py
estado global partilhado entre routes — utilizadores em memoria
"""

import logging
import sqlite3

from app.services.database import DB_PATH, get_db_connection

logger = logging.getLogger("metric4.api")

UTILIZADORES: dict[str, dict] = {}


def carregar_utilizadores_db() -> dict[str, dict]:
    utilizadores: dict[str, dict] = {}
    try:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT username, password, cliente_id FROM users"
            ).fetchall()
        for row in rows:
            utilizadores[row["username"]] = {
                "password": row["password"],
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
            "Corre database_setup.py ou reinicia a API apos migracao."
        ) from exc
    return utilizadores


def reload_utilizadores() -> None:
    global UTILIZADORES
    UTILIZADORES = carregar_utilizadores_db()
