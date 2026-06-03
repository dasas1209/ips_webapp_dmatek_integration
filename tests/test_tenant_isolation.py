"""
tests/test_tenant_isolation.py
isolamento multi-tenant (critico):
- tenant A nao acede a dados de tenant B
- tenant_id e sempre lido do JWT, nunca do request body/url
"""

from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from config import SECRET_KEY, ALGORITHM
from tests.conftest import _test_db_ctx, mock_influx


def _token(tenant_id: str, role: str = "user", username: str = "user") -> str:
    payload = {
        "sub": username,
        "tenant_id": tenant_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _auth(tenant_id: str, role: str = "user") -> dict:
    return {"Authorization": f"Bearer {_token(tenant_id, role)}"}


@pytest.fixture(scope="module")
def client():
    with (
        patch("app.services.database.get_db_connection", side_effect=_test_db_ctx),
        patch("app.services.influx_client.get_influx_client", return_value=mock_influx()),
        patch("app.dependencies.get_influx_client", return_value=mock_influx()),
        patch("app.routes.realtime.get_influx_client", return_value=mock_influx()),
        patch("app.routes.kpis.get_influx_client", return_value=mock_influx()),
    ):
        import app.state as state
        state.UTILIZADORES = {
            "admin":  {"password": "admin",  "tenant_id": "cliente_admin"},
            "user_a": {"password": "pass_a", "tenant_id": "tenant_a"},
            "user_b": {"password": "pass_b", "tenant_id": "tenant_b"},
        }
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestTenantIdVemDoJWT:
    """o tenant_id nunca deve ser aceite do request — deve vir sempre do JWT"""

    def test_posicoes_usa_tenant_da_sessao(self, client):
        """mesmo que o request nao especifique tenant, usa o do token"""
        r = client.get("/posicoes", headers=_auth("tenant_a"))
        assert r.status_code == 200

    def test_kpis_usa_tenant_da_sessao(self, client):
        r = client.get("/kpis", headers=_auth("tenant_a"))
        assert r.status_code == 200

    def test_tenant_invalido_no_token_retorna_401(self, client):
        """tenant_id que nao passa validacao de caracteres deve ser rejeitado"""
        # tenant_id com caracteres invalidos (injecao de flux)
        token = _token("../../../etc/passwd")
        r = client.get("/posicoes", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code in (400, 401, 403, 422)


class TestIsolamentoDeMapas:
    def test_mapas_de_tenant_a_nao_vistos_por_tenant_b(self, client):
        """GET /api/mapas deve devolver apenas mapas do tenant autenticado"""
        r_a = client.get("/api/mapas", headers=_auth("tenant_a"))
        r_b = client.get("/api/mapas", headers=_auth("tenant_b"))
        assert r_a.status_code == 200
        assert r_b.status_code == 200

        mapas_a = {m["nome"] for m in r_a.json()}
        mapas_b = {m["nome"] for m in r_b.json()}

        assert "Mapa A" in mapas_a,  "tenant_a devia ver 'Mapa A'"
        assert "Mapa B" not in mapas_a, "tenant_a NAO devia ver 'Mapa B'"
        assert "Mapa B" in mapas_b,  "tenant_b devia ver 'Mapa B'"
        assert "Mapa A" not in mapas_b, "tenant_b NAO devia ver 'Mapa A'"

    def test_config_tenant_a_nao_acessivel_por_tenant_b(self, client):
        """admin de tenant_b nao acede ao config de tenant_a"""
        token_b = _token("tenant_b", role="admin", username="user_b")
        r = client.get("/api/admin/config/tenant_a",
                       headers={"Authorization": f"Bearer {token_b}"})
        assert r.status_code == 403


class TestIsolamentoDeAdmin:
    def test_admin_endpoint_requer_superadmin(self, client):
        """user normal nao acede a /api/admin/tenants"""
        r = client.get("/api/admin/tenants", headers=_auth("tenant_a", role="user"))
        assert r.status_code == 403

    def test_admin_endpoint_acessivel_por_superadmin(self, client):
        r = client.get("/api/admin/tenants",
                       headers=_auth("cliente_admin", role="superadmin"))
        assert r.status_code == 200

    def test_audit_log_requer_superadmin(self, client):
        r = client.get("/admin/audit-log", headers=_auth("tenant_a", role="user"))
        assert r.status_code == 403

    def test_audit_log_acessivel_por_superadmin(self, client):
        r = client.get("/admin/audit-log",
                       headers=_auth("cliente_admin", role="superadmin"))
        assert r.status_code == 200

    def test_manipulacao_tenant_id_no_url_retorna_403(self, client):
        """admin de tenant_a nao pode criar user em tenant_b via body"""
        token_a = _token("tenant_a", role="admin", username="user_a")
        r = client.post(
            "/api/admin/users",
            json={"username": "hacker", "password": "x", "tenant_id": "tenant_b"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert r.status_code == 403


class TestBranding:
    def test_branding_retorna_tenant_da_sessao(self, client):
        r = client.get("/api/tenant/branding", headers=_auth("tenant_a"))
        assert r.status_code == 200
        body = r.json()
        assert body["tenant_id"] == "tenant_a"
        assert body["nome"] == "Empresa A"

    def test_branding_tenant_b_nao_ve_dados_de_a(self, client):
        r = client.get("/api/tenant/branding", headers=_auth("tenant_b"))
        assert r.status_code == 200
        body = r.json()
        assert body["tenant_id"] == "tenant_b"
        assert body["nome"] != "Empresa A"
