"""
config.py
configuracao centralizada do sistema metric4 rtls
"""

import os
from dotenv import load_dotenv

load_dotenv()

# configuracao do influxdb
INFLUX_URL    = os.getenv("INFLUX_URL")
INFLUX_TOKEN  = os.getenv("INFLUX_TOKEN")
INFLUX_ORG    = os.getenv("INFLUX_ORG")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET")

# configuracao de autenticacao jwt
SECRET_KEY         = os.getenv("SECRET_KEY", "chave-provisoria-para-teste")
ALGORITHM          = "HS256"
TOKEN_EXPIRY_HOURS = int(os.getenv("TOKEN_EXPIRY_HOURS", "2"))

ADMIN_TENANT_ID = os.getenv("ADMIN_TENANT_ID", "cliente_admin")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# dimensoes fisicas da fabrica em centimetros
LIMITE_X_CM = float(os.getenv("LIMITE_X_CM", "760.0"))
LIMITE_Y_CM = float(os.getenv("LIMITE_Y_CM", "500.0"))

# distancia minima entre leituras para contar como movimento
LIMIAR_MOVIMENTO_CM = float(os.getenv("LIMIAR_MOVIMENTO_CM", "50.0"))

# tempos limite em segundos para marcar tag como offline
TIMEOUT_MOVIMENTO = int(os.getenv("TIMEOUT_MOVIMENTO", "1"))
TIMEOUT_REPOUSO   = int(os.getenv("TIMEOUT_REPOUSO", "70"))

# janelas temporais de analise em horas e dias
JANELA_KPI_HORAS      = int(os.getenv("JANELA_KPI_HORAS", "8"))
LIMITE_DIAS_HISTORICO = int(os.getenv("LIMITE_DIAS_HISTORICO", "30"))

# limite de pontos no heatmap do frontend
MAX_RASTO_PONTOS = int(os.getenv("MAX_RASTO_PONTOS", "5000"))

# configuracao do servidor websocket dmatek
IP_SERVIDOR_DMATEK = os.getenv("IP_SERVIDOR_DMATEK", "172.16.0.201")
PORTA_DMATEK       = os.getenv("PORTA_DMATEK", "5002")
ENDPOINT_DMATEK    = os.getenv("ENDPOINT_DMATEK", "/TagPosition")

# origens permitidas para cors — configuravel via CORS_ORIGINS no .env (valores separados por virgula)
# ex: CORS_ORIGINS=http://localhost:8000,https://rtls.metric4.pt
_cors_env = os.getenv("CORS_ORIGINS", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _cors_env.split(",") if o.strip()]
    or ["http://localhost:8000", "http://127.0.0.1:8000"]
)
