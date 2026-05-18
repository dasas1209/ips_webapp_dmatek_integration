"""
database_setup.py
inicializacao e seeding da base de dados sqlite3 do sistema metric4 rtls
"""

import csv
import logging
import sqlite3
from pathlib import Path

from services.database import get_db_connection
from config import ADMIN_TENANT_ID, ADMIN_USERNAME, ADMIN_PASSWORD

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("metric4.db_setup")

# caminho canonico da base de dados (sempre relativo ao script)
BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "metric4rtls_system.db"

# csvs de origem — apagados apos seeding bem-sucedido
CSV_CLIENTES  = BASE_DIR / "matriz_clientes.csv"
CSV_MAPAS     = BASE_DIR / "matriz_mapas.csv"
CSV_USUARIOS  = BASE_DIR / "utilizadores_placeholder.csv"


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def create_tables(conn: sqlite3.Connection) -> None:
    """cria todas as tabelas se nao existirem"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS clientes (
            id          TEXT PRIMARY KEY,
            nome        TEXT NOT NULL,
            logo_url    TEXT,
            password    TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT NOT NULL UNIQUE,
            password    TEXT NOT NULL,
            cliente_id  TEXT NOT NULL REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS mapas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nome        TEXT NOT NULL,
            limite_x    REAL NOT NULL,
            limite_y    REAL NOT NULL,
            ficheiro_dxf TEXT,
            ficheiro_img TEXT,
            cliente_id  TEXT NOT NULL REFERENCES clientes(id)
        );

        CREATE TABLE IF NOT EXISTS ancoras (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            id_fisico   TEXT NOT NULL,
            mapa_id     INTEGER NOT NULL REFERENCES mapas(id),
            coord_x     REAL NOT NULL,
            coord_y     REAL NOT NULL,
            coord_z     REAL NOT NULL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS tags (
            id_fisico   TEXT PRIMARY KEY,
            nome        TEXT NOT NULL,
            cliente_id  TEXT NOT NULL REFERENCES clientes(id)
        );
    """)
    conn.commit()
    logger.info("tabelas verificadas/criadas.")


# ---------------------------------------------------------------------------
# verificacao de estado
# ---------------------------------------------------------------------------

def check_db_initialized(conn: sqlite3.Connection) -> bool:
    """
    devolve True se a bd ja contem dados (seeding ja correu).
    verifica a tabela clientes — se tiver pelo menos 1 registo, assume bd pronta.
    """
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM clientes").fetchone()
        return row["n"] > 0
    except sqlite3.OperationalError:
        # tabela nao existe ainda
        return False


# ---------------------------------------------------------------------------
# seeding a partir dos csvs
# ---------------------------------------------------------------------------

def _seed_clientes_e_tags(conn: sqlite3.Connection) -> None:
    """popula clientes e tags a partir do csv matriz_clientes.csv"""
    if not CSV_CLIENTES.exists():
        logger.warning("csv matriz_clientes.csv nao encontrado — sem tags/clientes seeded.")
        return

    clientes_vistos: set[str] = set()

    with open(CSV_CLIENTES, encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for linha in reader:
            tag_id    = linha.get("tag_id",    "").strip()
            tenant_id = linha.get("tenant_id", "").strip()
            descricao = linha.get("descricao", "").strip()

            if not tag_id or not tenant_id:
                continue

            # cria cliente se ainda nao existe
            if tenant_id not in clientes_vistos:
                conn.execute(
                    "INSERT OR IGNORE INTO clientes (id, nome) VALUES (?, ?)",
                    (tenant_id, tenant_id.replace("_", " ").title()),
                )
                clientes_vistos.add(tenant_id)

            # insere tag
            conn.execute(
                "INSERT OR IGNORE INTO tags (id_fisico, nome, cliente_id) VALUES (?, ?, ?)",
                (tag_id, descricao or tag_id, tenant_id),
            )

    conn.commit()
    logger.info("clientes seeded: %s | tags seeded a partir do csv.", len(clientes_vistos))


def _seed_mapas(conn: sqlite3.Connection) -> None:
    """popula mapas a partir de um CSV externo para evitar sementes fixas."""

    if not CSV_MAPAS.exists():
        logger.warning("csv matriz_mapas.csv nao encontrado — sem mapas seeded.")
        return

    count = 0
    with open(CSV_MAPAS, encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for linha in reader:
            nome = linha.get("nome", "").strip()
            limite_x = linha.get("limite_x", "").strip()
            limite_y = linha.get("limite_y", "").strip()
            ficheiro = linha.get("ficheiro_img", "").strip() or None
            cliente_id = linha.get("cliente_id", "").strip()

            if not nome or not limite_x or not limite_y or not cliente_id:
                continue

            try:
                lx = float(limite_x)
                ly = float(limite_y)
            except ValueError:
                logger.warning("linha de mapa invalida ignorada: %s", linha)
                continue

            existe = conn.execute(
                "SELECT 1 FROM clientes WHERE id = ?", (cliente_id,)
            ).fetchone()
            if not existe:
                logger.warning("cliente de mapa nao encontrado, ignorando: %s", cliente_id)
                continue

            conn.execute(
                "INSERT OR IGNORE INTO mapas (nome, limite_x, limite_y, ficheiro_img, cliente_id) VALUES (?, ?, ?, ?, ?)",
                (nome, lx, ly, ficheiro, cliente_id),
            )
            count += 1

    conn.commit()
    logger.info("mapas seeded: %s", count)


def _seed_usuarios(conn: sqlite3.Connection) -> None:
    """popula utilizadores a partir do csv utilizadores_placeholder.csv"""
    if not CSV_USUARIOS.exists():
        logger.warning("csv utilizadores_placeholder.csv nao encontrado — sem utilizadores seeded.")
        return

    count = 0
    with open(CSV_USUARIOS, encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for linha in reader:
            username  = linha.get("username",  "").strip()
            password  = linha.get("password",  "").strip()
            tenant_id = linha.get("tenant_id", "").strip()

            if not username or not password or not tenant_id:
                continue

            # garante que o cliente existe antes de inserir FK
            conn.execute(
                "INSERT OR IGNORE INTO clientes (id, nome) VALUES (?, ?)",
                (tenant_id, tenant_id.replace("_", " ").title()),
            )
            conn.execute(
                "INSERT OR IGNORE INTO users (username, password, cliente_id) VALUES (?, ?, ?)",
                (username, password, tenant_id),
            )
            count += 1

    conn.commit()
    logger.info("utilizadores seeded: %s", count)


def seed_from_csvs(conn: sqlite3.Connection) -> None:
    """orquestra o seeding completo a partir dos csvs existentes"""
    logger.info("a fazer seeding da base de dados a partir dos CSVs...")
    _seed_clientes_e_tags(conn)
    _seed_mapas(conn)
    _seed_usuarios(conn)


# ---------------------------------------------------------------------------
# admin idempotente
# ---------------------------------------------------------------------------

def ensure_admin(conn: sqlite3.Connection) -> None:
    """
    garante que existe um cliente admin e um user administrador configurado por ambiente.
    idempotente — nao duplica se ja existir.
    """
    conn.execute(
        "INSERT OR IGNORE INTO clientes (id, nome) VALUES (?, ?)",
        (ADMIN_TENANT_ID, "Administrador"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO users (username, password, cliente_id) VALUES (?, ?, ?)",
        (ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_TENANT_ID),
    )
    conn.commit()

    # log diferenciado: admin criado ou ja existia
    admin = conn.execute(
        "SELECT id FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()
    if admin:
        logger.info("utilizador admin verificado (id=%s).", admin["id"])


# ---------------------------------------------------------------------------
# limpeza de csvs apos seeding bem-sucedido
# ---------------------------------------------------------------------------

def delete_csvs() -> None:
    """apaga os csvs de origem apos seeding — os dados vivem na bd a partir de agora"""
    for csv_path in (CSV_CLIENTES, CSV_MAPAS, CSV_USUARIOS):
        if csv_path.exists():
            csv_path.unlink()
            logger.info("csv apagado: %s", csv_path.name)


# ---------------------------------------------------------------------------
# ponto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("=== Metric4 DB Setup ===")
    logger.info("base de dados: %s", DB_PATH)

    try:
        conn = get_db_connection()
    except sqlite3.Error as exc:
        logger.error("nao foi possivel abrir a base de dados: %s", exc)
        raise SystemExit(1) from exc

    with conn:
        create_tables(conn)

        if check_db_initialized(conn):
            logger.info("Database OK — seeding ignorado.")
        else:
            seed_from_csvs(conn)
            delete_csvs()
            logger.info("Database seeded com sucesso.")

        # admin e sempre verificado (independente do seeding)
        ensure_admin(conn)

    conn.close()
    logger.info("=== Setup concluido ===")


if __name__ == "__main__":
    main()
