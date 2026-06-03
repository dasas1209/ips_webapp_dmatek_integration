"""
scripts/database_setup.py
inicializacao e seeding da base de dados sqlite3 do sistema metric4 rtls
"""

import csv
import logging
import sqlite3
from pathlib import Path

from app.services.database import get_db_connection
from config import ADMIN_PASSWORD, ADMIN_TENANT_ID, ADMIN_USERNAME

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("metric4.db_setup")

BASE_DIR = Path(__file__).parent.parent
DB_PATH  = BASE_DIR / "metric4rtls_system.db"

# csvs de origem apagados apos carregamento bem-sucedido
CSV_CLIENTES = BASE_DIR / "matriz_clientes.csv"
CSV_MAPAS    = BASE_DIR / "matriz_mapas.csv"
CSV_USUARIOS = BASE_DIR / "utilizadores_placeholder.csv"


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
    logger.info("tabelas verificadas/criadas")


def check_db_initialized(conn: sqlite3.Connection) -> bool:
    """devolve True se a bd ja contem dados (pelo menos 1 cliente)"""
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM clientes").fetchone()
        return row["n"] > 0
    except sqlite3.OperationalError:
        return False


def _seed_clientes_e_tags(conn: sqlite3.Connection) -> None:
    """popula clientes e tags a partir do csv matriz_clientes.csv"""
    if not CSV_CLIENTES.exists():
        logger.warning("csv matriz_clientes.csv nao encontrado — sem tags carregadas")
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

            if tenant_id not in clientes_vistos:
                conn.execute(
                    "INSERT OR IGNORE INTO clientes (id, nome) VALUES (?, ?)",
                    (tenant_id, tenant_id.replace("_", " ").title()),
                )
                clientes_vistos.add(tenant_id)

            conn.execute(
                "INSERT OR IGNORE INTO tags (id_fisico, nome, cliente_id) VALUES (?, ?, ?)",
                (tag_id, descricao or tag_id, tenant_id),
            )

    conn.commit()
    logger.info("clientes carregados: %s | tags carregadas a partir do csv", len(clientes_vistos))


def _seed_mapas(conn: sqlite3.Connection) -> None:
    """popula mapas a partir do csv matriz_mapas.csv"""
    if not CSV_MAPAS.exists():
        logger.warning("csv matriz_mapas.csv nao encontrado — sem mapas carregados")
        return

    count = 0
    with open(CSV_MAPAS, encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for linha in reader:
            nome       = linha.get("nome",        "").strip()
            limite_x   = linha.get("limite_x",    "").strip()
            limite_y   = linha.get("limite_y",    "").strip()
            ficheiro   = linha.get("ficheiro_img","").strip() or None
            cliente_id = linha.get("cliente_id",  "").strip()

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
    logger.info("mapas carregados: %s", count)


def _seed_usuarios(conn: sqlite3.Connection) -> None:
    """popula utilizadores a partir do csv utilizadores_placeholder.csv"""
    if not CSV_USUARIOS.exists():
        logger.warning("csv utilizadores_placeholder.csv nao encontrado — sem utilizadores carregados")
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

            # garante fk valida antes de inserir o utilizador
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
    logger.info("utilizadores carregados: %s", count)


def seed_from_csvs(conn: sqlite3.Connection) -> None:
    """orquestra o carregamento completo a partir dos csvs existentes"""
    logger.info("a carregar base de dados a partir dos csvs")
    _seed_clientes_e_tags(conn)
    _seed_mapas(conn)
    _seed_usuarios(conn)


def _normalizar_path_mapa(path: str) -> str:
    """converte caminhos legados para /static/assets/imgs/maps/<ficheiro>"""
    if not path:
        return path
    p = path.strip().replace("\\", "/")
    if p.startswith("/static/assets/imgs/maps/"):
        return p
    if "metric-logo" in p:
        return "/static/assets/imgs/metric-logo.svg"
    nome = p.split("/")[-1]
    if nome and "." in nome:
        return f"/static/assets/imgs/maps/{nome}"
    return p


def migrate_asset_paths(conn: sqlite3.Connection) -> None:
    """actualiza ficheiro_img e logo_url para a nova estrutura de pastas"""
    alterados = 0

    for row in conn.execute(
        "SELECT id, ficheiro_img FROM mapas WHERE ficheiro_img IS NOT NULL AND ficheiro_img != ''"
    ).fetchall():
        novo = _normalizar_path_mapa(row["ficheiro_img"])
        if novo != row["ficheiro_img"]:
            conn.execute("UPDATE mapas SET ficheiro_img = ? WHERE id = ?", (novo, row["id"]))
            alterados += 1

    for row in conn.execute(
        "SELECT id, logo_url FROM clientes WHERE logo_url IS NOT NULL AND logo_url != ''"
    ).fetchall():
        url = row["logo_url"].strip().replace("\\", "/")
        if "metric-logo" in url:
            novo = "/static/assets/imgs/metric-logo.svg"
        elif url.startswith("/static/assets/imgs/avatars/"):
            novo = url
        elif url.startswith("/static/assets/avatars/"):
            novo = url.replace("/static/assets/avatars/", "/static/assets/imgs/avatars/")
        elif url.startswith("frontend/assets/imgs/avatars/"):
            novo = url.replace("frontend/", "/static/")
        elif url.startswith("frontend/assets/avatars/"):
            novo = url.replace("frontend/assets/avatars/", "/static/assets/imgs/avatars/")
        elif "/" in url:
            nome = url.split("/")[-1]
            novo = f"/static/assets/imgs/avatars/{nome}"
        else:
            novo = f"/static/assets/imgs/avatars/{url}"

        if novo != row["logo_url"]:
            conn.execute("UPDATE clientes SET logo_url = ? WHERE id = ?", (novo, row["id"]))
            alterados += 1

    if alterados:
        conn.commit()
        logger.info("caminhos de imagens migrados: %s registo(s)", alterados)


def ensure_admin(conn: sqlite3.Connection) -> None:
    """garante que existe um cliente admin e utilizador administrador configurado por ambiente"""
    cliente_existe = conn.execute(
        "SELECT 1 FROM clientes WHERE id = ?", (ADMIN_TENANT_ID,)
    ).fetchone()
    user_existe = conn.execute(
        "SELECT 1 FROM users WHERE username = ?", (ADMIN_USERNAME,)
    ).fetchone()

    if cliente_existe and user_existe:
        logger.info("admin verificado — sem alteracoes necessarias")
        return

    # so chega aqui na primeira execucao ou se os registos foram apagados
    if not cliente_existe:
        conn.execute(
            "INSERT INTO clientes (id, nome) VALUES (?, ?)",
            (ADMIN_TENANT_ID, "Administrador"),
        )
    if not user_existe:
        conn.execute(
            "INSERT INTO users (username, password, cliente_id) VALUES (?, ?, ?)",
            (ADMIN_USERNAME, ADMIN_PASSWORD, ADMIN_TENANT_ID),
        )
    conn.commit()
    logger.info("admin criado com sucesso")


def delete_csvs() -> None:
    """apaga os csvs de origem apos carregamento — os dados vivem na bd a partir de agora"""
    for csv_path in (CSV_CLIENTES, CSV_MAPAS, CSV_USUARIOS):
        if csv_path.exists():
            csv_path.unlink()
            logger.info("csv apagado: %s", csv_path.name)


def main() -> None:
    logger.info("=== metric4 db setup ===")
    logger.info("base de dados: %s", DB_PATH)

    try:
        conn = get_db_connection()
    except sqlite3.Error as exc:
        logger.error("nao foi possivel abrir a base de dados: %s", exc)
        raise SystemExit(1) from exc

    try:
        with conn:
            create_tables(conn)

            if check_db_initialized(conn):
                logger.info("base de dados ja inicializada — carregamento ignorado")
            else:
                seed_from_csvs(conn)
                delete_csvs()
                logger.info("base de dados carregada com sucesso")

            # admin verificado independentemente do carregamento inicial
            ensure_admin(conn)
            migrate_asset_paths(conn)

    except sqlite3.OperationalError as exc:
        if "database is locked" in str(exc).lower():
            # bd ja inicializada em sessoes anteriores — termina sem erro
            logger.info("bd em uso por outro processo — assumindo ja inicializada")
        else:
            logger.error("erro inesperado na bd: %s", exc)
            raise SystemExit(1) from exc
    finally:
        conn.close()

    logger.info("=== arranque concluido ===")


if __name__ == "__main__":
    main()
