"""
tests/test_imports.py
verifica que todos os modulos python resolvem sem ModuleNotFoundError
"""

import importlib
import pytest


MODULES = [
    "config",
    "app",
    "app.main",
    "app.models",
    "app.dependencies",
    "app.state",
    "app.routes.auth",
    "app.routes.realtime",
    "app.routes.kpis",
    "app.routes.admin",
    "app.routes.audit",
    "app.routes.tenant",
    "app.services.database",
    "app.services.influx_client",
    "app.services.kpi_engine",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_importa_sem_erro(module):
    """todos os modulos da aplicacao devem importar sem erros"""
    mod = importlib.import_module(module)
    assert mod is not None
