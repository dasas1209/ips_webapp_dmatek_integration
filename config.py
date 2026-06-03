"""
config.py
configuracao centralizada do sistema metric4 rtls
todas as constantes sao configuraveis via variaveis de ambiente no .env
ver .env.example para documentacao completa de cada variavel
"""

import os
from dotenv import load_dotenv

load_dotenv()

# influxdb

INFLUX_URL    = os.getenv("INFLUX_URL")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN")
INFLUX_ORG    = os.getenv("INFLUX_ORG")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET")

# autenticacao jwt

_secret = os.getenv("SECRET_KEY")
if not _secret:
    raise RuntimeError(
        "SECRET_KEY nao definida no .env — necessaria para assinar JWT.\n"
        "Gera uma chave segura com: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
SECRET_KEY         = _secret
ALGORITHM          = "HS256"
TOKEN_EXPIRY_HOURS = int(os.getenv("TOKEN_EXPIRY_HOURS", "2"))

# conta administrador do sistema

ADMIN_TENANT_ID = os.getenv("ADMIN_TENANT_ID", "cliente_admin")
ADMIN_USERNAME  = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD  = os.getenv("ADMIN_PASSWORD", "admin")

# fallback de limites quando o cliente nao tem mapa na bd

LIMITE_X_CM = float(os.getenv("LIMITE_X_CM", "760.0"))
LIMITE_Y_CM = float(os.getenv("LIMITE_Y_CM", "500.0"))

# motor de kpis e deteccao de movimento

# distancia minima entre leituras para contar como movimento (cm)
LIMIAR_MOVIMENTO_CM = float(os.getenv("LIMIAR_MOVIMENTO_CM", "50.0"))

# segundos sem sinal para marcar tag em movimento como offline
TIMEOUT_MOVIMENTO = int(os.getenv("TIMEOUT_MOVIMENTO", "1"))

# segundos sem sinal para marcar tag em repouso como offline
TIMEOUT_REPOUSO   = int(os.getenv("TIMEOUT_REPOUSO", "70"))

# janela de analise do turno actual em horas
JANELA_KPI_HORAS = int(os.getenv("JANELA_KPI_HORAS", "8"))

# maximo de dias de historico consultavel via /relatorio/dados
LIMITE_DIAS_HISTORICO = int(os.getenv("LIMITE_DIAS_HISTORICO", "30"))

# maximo de pontos de rasto enviados ao frontend por query
MAX_RASTO_PONTOS = int(os.getenv("MAX_RASTO_PONTOS", "5000"))

# worker de escuta dmatek

# ip do servidor websocket dmatek (rede interna da fabrica)
IP_SERVIDOR_DMATEK = os.getenv("IP_SERVIDOR_DMATEK", "172.16.0.201")
PORTA_DMATEK       = os.getenv("PORTA_DMATEK", "5002")
ENDPOINT_DMATEK    = os.getenv("ENDPOINT_DMATEK", "/TagPosition")

# intervalo em segundos entre recargas do mapeamento tag->tenant da bd
MATRIZ_RELOAD_INTERVAL_SEG = int(os.getenv("MATRIZ_RELOAD_INTERVAL_SEG", "300"))

# limites de upload e queries influx

# tamanho maximo do ficheiro de avatar em bytes (default: 2 MB)
MAX_AVATAR_BYTES = int(os.getenv("MAX_AVATAR_BYTES", str(2 * 1024 * 1024)))

# maximo de registos devolvidos pelo log de auditoria global (/admin/audit-log)
AUDIT_LOG_INFLUX_LIMIT = int(os.getenv("AUDIT_LOG_INFLUX_LIMIT", "10000"))

# maximo de registos devolvidos pelo log de sessoes por tenant
SESSIONS_LOG_LIMIT = int(os.getenv("SESSIONS_LOG_LIMIT", "500"))

# identificacao do build (exibida no /api/health e no startup log)

API_BUILD_ID = os.getenv("API_BUILD_ID", "dev")

# cors

# origens permitidas separadas por virgula no .env
# ex: CORS_ORIGINS=http://localhost:8000,https://rtls.metric4.pt
_cors_env = os.getenv("CORS_ORIGINS", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _cors_env.split(",") if o.strip()]
    or ["http://localhost:8000", "http://127.0.0.1:8000"]
)
