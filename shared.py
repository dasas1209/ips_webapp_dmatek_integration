"""
shared.py
shim de compatibilidade — conteudo movido para services/database.py
importa e re-exporta para nao quebrar importacoes legadas
"""

from services.database import (  # noqa: F401
    carregar_matriz_clientes,
    get_db_connection,
    obter_limites_mapa,
    validar_tenant_id,
)
