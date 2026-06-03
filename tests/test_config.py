"""
tests/test_config.py
verifica carregamento de configuracao e cobertura do .env.example
"""

import re
from pathlib import Path

import pytest


def test_config_carrega_sem_erro():
    import config
    assert config is not None


def test_constantes_criticas_definidas():
    import config
    assert config.SECRET_KEY, "SECRET_KEY vazia"
    assert config.INFLUX_URL, "INFLUX_URL vazia"
    assert config.INFLUX_TOKEN, "INFLUX_TOKEN vazia"
    assert config.INFLUX_ORG, "INFLUX_ORG vazia"
    assert config.INFLUX_BUCKET, "INFLUX_BUCKET vazia"


def test_constantes_numericas_com_valores_razoaveis():
    import config
    assert config.TOKEN_EXPIRY_HOURS > 0
    assert config.LIMIAR_MOVIMENTO_CM > 0
    assert config.TIMEOUT_MOVIMENTO > 0
    assert config.TIMEOUT_REPOUSO > 0
    assert config.JANELA_KPI_HORAS > 0
    assert config.LIMITE_DIAS_HISTORICO > 0
    assert config.MAX_RASTO_PONTOS > 0
    assert config.MATRIZ_RELOAD_INTERVAL_SEG > 0
    assert config.MAX_AVATAR_BYTES > 0
    assert config.AUDIT_LOG_INFLUX_LIMIT > 0
    assert config.SESSIONS_LOG_LIMIT > 0
    assert config.LIMITE_X_CM > 0
    assert config.LIMITE_Y_CM > 0


def test_allowed_origins_nao_vazio():
    import config
    assert isinstance(config.ALLOWED_ORIGINS, list)
    assert len(config.ALLOWED_ORIGINS) > 0


def test_env_example_cobre_todas_as_variaveis_do_config():
    """todas as variaveis lidas por os.getenv() em config.py devem estar documentadas no .env.example"""
    root = Path(__file__).parent.parent

    config_src = (root / "config.py").read_text(encoding="utf-8")
    vars_no_codigo = set(re.findall(r'os\.getenv\(\s*"([A-Z_]+)"', config_src))

    example = (root / ".env.example").read_text(encoding="utf-8")
    vars_no_exemplo = set(re.findall(r'^#?\s*([A-Z_]+)=', example, re.MULTILINE))

    nao_documentadas = vars_no_codigo - vars_no_exemplo
    assert not nao_documentadas, (
        f"variaveis em config.py nao documentadas no .env.example: {nao_documentadas}"
    )


def test_admin_password_nao_e_default_em_producao():
    """verifica que a password admin nao esta com o default em ambiente de producao
    (o teste passa sempre em dev onde API_BUILD_ID=test)"""
    import os
    import config
    build = os.getenv("API_BUILD_ID", "dev")
    if build not in ("dev", "test"):
        assert config.ADMIN_PASSWORD != "admin", (
            "ADMIN_PASSWORD esta com o valor default 'admin' em ambiente de producao"
        )
