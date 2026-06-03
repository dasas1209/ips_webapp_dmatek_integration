"""
tests/conftest.py
fixtures partilhadas — env vars e bd de teste devem estar definidos
antes de qualquer import da aplicacao
"""

import os
import sqlite3
from contextlib import contextmanager
from unittest.mock import MagicMock

# env vars minimas para o config.py nao lancar RuntimeError
os.environ.setdefault("SECRET_KEY", "test-secret-key-para-testes-32-chars-abc")
os.environ.setdefault("INFLUX_URL",    "http://localhost:8086")
os.environ.setdefault("INFLUX_TOKEN",  "test-token")
os.environ.setdefault("INFLUX_ORG",    "test-org")
os.environ.setdefault("INFLUX_BUCKET", "test-bucket")
os.environ.setdefault("API_BUILD_ID",  "test")

import pytest


SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS clientes (
        id TEXT PRIMARY KEY, nome TEXT NOT NULL,
        logo_url TEXT, password TEXT
    );
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        cliente_id TEXT NOT NULL REFERENCES clientes(id)
    );
    CREATE TABLE IF NOT EXISTS mapas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL, limite_x REAL NOT NULL, limite_y REAL NOT NULL,
        ficheiro_dxf TEXT, ficheiro_img TEXT,
        cliente_id TEXT NOT NULL REFERENCES clientes(id)
    );
    CREATE TABLE IF NOT EXISTS ancoras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        id_fisico TEXT NOT NULL, mapa_id INTEGER NOT NULL REFERENCES mapas(id),
        coord_x REAL NOT NULL, coord_y REAL NOT NULL,
        coord_z REAL NOT NULL DEFAULT 0.0
    );
    CREATE TABLE IF NOT EXISTS tags (
        id_fisico TEXT PRIMARY KEY, nome TEXT NOT NULL,
        cliente_id TEXT NOT NULL REFERENCES clientes(id)
    );
"""

SEED_SQL = [
    "INSERT INTO clientes (id, nome, password) VALUES ('cliente_admin', 'Admin', 'admin')",
    "INSERT INTO clientes (id, nome, password) VALUES ('tenant_a', 'Empresa A', 'pass_a')",
    "INSERT INTO clientes (id, nome, password) VALUES ('tenant_b', 'Empresa B', 'pass_b')",
    "INSERT INTO users (username, password, cliente_id) VALUES ('admin',  'admin',  'cliente_admin')",
    "INSERT INTO users (username, password, cliente_id) VALUES ('user_a', 'pass_a', 'tenant_a')",
    "INSERT INTO users (username, password, cliente_id) VALUES ('user_b', 'pass_b', 'tenant_b')",
    "INSERT INTO mapas (nome, limite_x, limite_y, ficheiro_img, cliente_id) VALUES ('Mapa A', 760.0, 500.0, '/static/assets/imgs/maps/mapa_a.png', 'tenant_a')",
    "INSERT INTO mapas (nome, limite_x, limite_y, ficheiro_img, cliente_id) VALUES ('Mapa B', 800.0, 600.0, '/static/assets/imgs/maps/mapa_b.png', 'tenant_b')",
    "INSERT INTO tags (id_fisico, nome, cliente_id) VALUES ('TAG001', 'Asset A1', 'tenant_a')",
    "INSERT INTO tags (id_fisico, nome, cliente_id) VALUES ('TAG002', 'Asset B1', 'tenant_b')",
]


def _build_test_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_SQL)
    for stmt in SEED_SQL:
        conn.execute(stmt)
    conn.commit()
    return conn


_TEST_DB: sqlite3.Connection | None = None


def get_test_db() -> sqlite3.Connection:
    global _TEST_DB
    if _TEST_DB is None:
        _TEST_DB = _build_test_db()
    return _TEST_DB


@contextmanager
def _test_db_ctx():
    """devolve a bd de teste como context manager (sem fechar)"""
    yield get_test_db()


def mock_influx():
    m = MagicMock()
    m.query_api.return_value.query.return_value = []
    m.write_api.return_value.write.return_value = None
    return m
