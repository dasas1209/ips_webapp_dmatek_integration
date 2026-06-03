"""
tests/test_auth.py
autenticacao: login, logout, sessao invalida, rate limit
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import _test_db_ctx, mock_influx


@pytest.fixture(scope="module")
def client():
    with (
        patch("app.services.database.get_db_connection", side_effect=_test_db_ctx),
        patch("app.services.influx_client.get_influx_client", return_value=mock_influx()),
        patch("app.dependencies.get_influx_client", return_value=mock_influx()),
    ):
        # popula cache de utilizadores com dados de teste
        import app.state as state
        state.UTILIZADORES = {
            "admin":  {"password": "admin",  "tenant_id": "cliente_admin"},
            "user_a": {"password": "pass_a", "tenant_id": "tenant_a"},
            "user_b": {"password": "pass_b", "tenant_id": "tenant_b"},
        }
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def _login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


class TestLogin:
    def test_login_valido_retorna_token(self, client):
        r = _login(client, "user_a", "pass_a")
        assert r.status_code == 200
        body = r.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["tenant_id"] == "tenant_a"

    def test_login_superadmin_retorna_role_superadmin(self, client):
        r = _login(client, "admin", "admin")
        assert r.status_code == 200
        assert r.json()["role"] == "superadmin"

    def test_login_password_errada_retorna_401(self, client):
        r = _login(client, "user_a", "password_errada")
        assert r.status_code == 401

    def test_login_utilizador_inexistente_retorna_401(self, client):
        r = _login(client, "nao_existe", "qualquer")
        assert r.status_code == 401

    def test_login_campos_vazios_retorna_422(self, client):
        r = client.post("/login", data={"username": "", "password": ""})
        assert r.status_code in (401, 422)


class TestTokenValidade:
    def test_token_invalido_retorna_401(self, client):
        r = client.get("/posicoes", headers={"Authorization": "Bearer token-invalido"})
        assert r.status_code == 401

    def test_sem_token_retorna_401(self, client):
        r = client.get("/posicoes")
        assert r.status_code == 401

    def test_token_expirado_retorna_401(self, client):
        # JWT com exp no passado
        from jose import jwt
        from config import SECRET_KEY, ALGORITHM
        from datetime import datetime, timezone, timedelta
        payload = {
            "sub": "user_a",
            "tenant_id": "tenant_a",
            "role": "user",
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        r = client.get("/posicoes", headers={"Authorization": f"Bearer {expired_token}"})
        assert r.status_code == 401


class TestLogout:
    def test_logout_com_token_valido_retorna_200(self, client):
        r = _login(client, "user_a", "pass_a")
        token = r.json()["access_token"]
        r2 = client.post("/logout", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r2.status_code == 200

    def test_logout_sem_token_retorna_401(self, client):
        r = client.post("/logout")
        assert r.status_code == 401
