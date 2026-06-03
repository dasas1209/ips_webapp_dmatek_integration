"""
tests/test_endpoints.py
verifica que todos os endpoints registados respondem sem 500
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from config import SECRET_KEY, ALGORITHM
from tests.conftest import _test_db_ctx, mock_influx


def _token(tenant_id: str, role: str = "user") -> str:
    return jwt.encode(
        {
            "sub": f"user_{tenant_id}",
            "tenant_id": tenant_id,
            "role": role,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


@pytest.fixture(scope="module")
def client():
    with (
        patch("app.services.database.get_db_connection", side_effect=_test_db_ctx),
        patch("app.services.influx_client.get_influx_client", return_value=mock_influx()),
        patch("app.dependencies.get_influx_client", return_value=mock_influx()),
        patch("app.routes.realtime.get_influx_client", return_value=mock_influx()),
        patch("app.routes.kpis.get_influx_client", return_value=mock_influx()),
        patch("app.routes.audit.get_influx_client", return_value=mock_influx()),
    ):
        import app.state as state
        state.UTILIZADORES = {
            "admin":  {"password": "admin",  "tenant_id": "cliente_admin"},
            "user_a": {"password": "pass_a", "tenant_id": "tenant_a"},
        }
        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def _h(tenant_id="tenant_a", role="user"):
    return {"Authorization": f"Bearer {_token(tenant_id, role)}"}


def _h_admin():
    return _h("cliente_admin", "superadmin")


class TestEndpointsNao500:
    """todos os endpoints devem responder com status code != 500"""

    # endpoints publicos / especiais
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200

    # autenticacao
    def test_login_endpoint(self, client):
        r = client.post("/login", data={"username": "user_a", "password": "pass_a"})
        assert r.status_code == 200

    def test_logout_endpoint(self, client):
        r = client.post("/logout", headers=_h())
        assert r.status_code == 200

    # dados em tempo real
    def test_posicoes(self, client):
        r = client.get("/posicoes", headers=_h())
        assert r.status_code not in (500,)

    def test_historico(self, client):
        r = client.get("/historico?minutos_atras=30", headers=_h())
        assert r.status_code not in (500,)

    # kpis
    def test_kpis(self, client):
        r = client.get("/kpis", headers=_h())
        assert r.status_code not in (500,)

    def test_relatorio_dados(self, client):
        inicio = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
        fim    = datetime.now(timezone.utc).isoformat()
        r = client.get(f"/relatorio/dados?inicio={inicio}&fim={fim}", headers=_h())
        assert r.status_code not in (500,)

    # mapas
    def test_api_mapas(self, client):
        r = client.get("/api/mapas", headers=_h())
        assert r.status_code not in (500,)

    # tenant
    def test_tenant_branding(self, client):
        r = client.get("/api/tenant/branding", headers=_h())
        assert r.status_code not in (500,)

    # admin (superadmin)
    def test_admin_tenants(self, client):
        r = client.get("/api/admin/tenants", headers=_h_admin())
        assert r.status_code not in (500,)

    def test_admin_config_tenant(self, client):
        r = client.get("/api/admin/config/tenant_a", headers=_h_admin())
        assert r.status_code not in (500,)

    def test_audit_log(self, client):
        r = client.get("/admin/audit-log", headers=_h_admin())
        assert r.status_code not in (500,)

    def test_sessions_por_tenant(self, client):
        r = client.get("/api/admin/tenants/tenant_a/sessions", headers=_h_admin())
        assert r.status_code not in (500,)

    # frontend servido pelo uvicorn (ficheiros estaticos existem)
    def test_serve_index(self, client):
        r = client.get("/app")
        assert r.status_code not in (500,)

    def test_serve_relatorio(self, client):
        r = client.get("/relatorio.html")
        assert r.status_code not in (500,)

    def test_serve_auditoria(self, client):
        r = client.get("/auditoria.html")
        assert r.status_code not in (500,)

    def test_serve_admin(self, client):
        r = client.get("/admin.html")
        assert r.status_code not in (500,)

    def test_serve_audit_log(self, client):
        r = client.get("/app/audit-log")
        assert r.status_code not in (500,)


class TestEndpointsRetornam404QuandoNaoExistem:
    def test_rota_inexistente_retorna_404(self, client):
        r = client.get("/rota-que-nao-existe")
        assert r.status_code == 404

    def test_admin_tenant_inexistente_retorna_200_com_arrays_vazios(self, client):
        # o endpoint nao verifica existencia do tenant — devolve 200 com listas vazias
        # isto e comportamento deliberado (ausencia de dados != recurso inexistente)
        r = client.get("/api/admin/config/tenant_nao_existe", headers=_h_admin())
        assert r.status_code == 200
        body = r.json()
        assert body["users"] == []
        assert body["mapas"] == []
        assert body["tags"] == []
