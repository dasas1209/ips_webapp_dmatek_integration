"""
shared.py
utilitarios partilhados entre api_dmatek.py e escuta_dmatek.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "metric4rtls_system.db"


def get_db_connection() -> sqlite3.Connection:
    """devolve ligacao sqlite com row_factory e fks activas"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def carregar_matriz_clientes() -> dict[str, str]:
    """
    le a tabela tags e devolve mapeamento {id_fisico: cliente_id}.
    substitui a leitura do csv matriz_clientes.csv.
    """
    matriz: dict[str, str] = {}
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT id_fisico, cliente_id FROM tags").fetchall()
        for row in rows:
            matriz[row["id_fisico"]] = row["cliente_id"]
        print(f"[INFO] Matriz carregada da BD: {len(matriz)} tag(s) mapeada(s).")
    except sqlite3.Error as exc:
        print(f"[ERRO] Falha ao ler matriz de clientes da BD: {exc}")
    return matriz


def obter_limites_mapa(cliente_id: str) -> tuple[float, float]:
    """
    devolve (limite_x, limite_y) do primeiro mapa associado ao cliente.
    fallback para os valores historicos caso o cliente nao tenha mapa registado.
    """
    try:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT limite_x, limite_y FROM mapas WHERE cliente_id = ? LIMIT 1",
                (cliente_id,),
            ).fetchone()
        if row:
            return float(row["limite_x"]), float(row["limite_y"])
    except sqlite3.Error as exc:
        print(f"[AVISO] Nao foi possivel obter limites do mapa para {cliente_id}: {exc}")

    # fallback defensivo: valores do config original
    from config import LIMITE_X_CM, LIMITE_Y_CM  # noqa: PLC0415
    return LIMITE_X_CM, LIMITE_Y_CM
