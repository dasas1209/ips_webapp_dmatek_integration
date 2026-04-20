from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from influxdb_client import InfluxDBClient # type: ignore
from pydantic import BaseModel
from jose import jwt
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY") 
ALGORITHM = "HS256" # O algoritmo matemático que "sela" o crachá

# 1. Carregar as chaves
load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "chave-provisoria-para-teste")

# 2. Inicializar o API
app = FastAPI(
    title="Portal de Dados RTLS Dmatek",
    description="API de Gestão Multi-Tenant para posições em tempo real.",
    version="1.0.0"
)

# permite que o HTML encontre o app.js
app.mount("/static", StaticFiles(directory="frontend"), name="static")

# --- MVP: SIMULADOR DE UTILIZADORES E CLIENTES ---
# Na Fase 4, isto virá de uma base de dados real (ex: PostgreSQL)
UTILIZADORES = {
    "gestor_a": {"password": "123", "tenant_id": "cliente_A"},
    "gestor_b": {"password": "456", "tenant_id": "cliente_B"}
}

# --- CONFIGURAÇÃO INFLUXDB ---
INFLUX_URL = os.getenv("INFLUX_URL")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
INFLUX_ORG = os.getenv("INFLUX_ORG")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET")

# Isto avisa a FastAPI que vamos usar um sistema de Tokens para segurança
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def verificar_cracha(token: str = Depends(oauth2_scheme)):
    try:
        # A API tenta abrir o Contentor Selado usando a Chave Mestra
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]) # type: ignore
        tenant_id = payload.get("tenant_id")
        
        if tenant_id is None:
            raise HTTPException(status_code=401, detail="Crachá sem identificação de cliente.")
            
        return tenant_id # Devolve o ID do cliente (ex: "cliente_A")
    except:
        # Se a assinatura for falsa ou o token estiver expirado, expulsa!
        raise HTTPException(status_code=401, detail="Acesso Negado: Crachá inválido ou expirado.")


# --- MOTOR DE SEGURANÇA ---
def criar_cracha_jwt(dados: dict):
    conteudo_a_guardar = dados.copy()
    
    # Define que o crachá expira daqui a 2 horas (Regra de Segurança)
    validade = datetime.utcnow() + timedelta(hours=2)
    conteudo_a_guardar.update({"exp": validade})
    
    # Gera o código encriptado
    token_gerado = jwt.encode(conteudo_a_guardar, SECRET_KEY, algorithm=ALGORITHM) # type: ignore
    return token_gerado

# 1ª Rota
@app.get("/")
def estado_do_sistema():
    return {
        "status": "Online", 
        "mensagem": "Porteiro da Fábrica Ativo. Sistema pronto a receber pedidos."
    }

# --- ROTAS DA API ---
@app.post("/login")
def login(credenciais: OAuth2PasswordRequestForm = Depends()):
    # 1. Procurar o utilizador no nosso "Excel"
    user_encontrado = UTILIZADORES.get(credenciais.username)
    
    # 2. Se não existir, expulsar (Erro 401)
    if not user_encontrado:
        raise HTTPException(status_code=401, detail="Utilizador não existe na fábrica.")
        
    # 3. Se a password estiver errada, expulsar
    if user_encontrado["password"] != credenciais.password:
        raise HTTPException(status_code=401, detail="Password incorreta.")
        
    # 4. Utilizador válido! Descobrir o cliente dele e cunhar o crachá
    id_do_cliente = user_encontrado["tenant_id"]
    
    dados_para_o_cracha = {
        "sub": credenciais.username, # sub = subject (quem é o dono do token)
        "tenant_id": id_do_cliente   # O nosso segredo multi-tenant!
    }
    
    meu_token = criar_cracha_jwt(dados_para_o_cracha)
    
    # 5. Entregar o crachá ao utilizador
    return {
        "access_token": meu_token, 
        "token_type": "bearer",
        "mensagem": f"Bem-vindo {credenciais.username}. O teu crachá foi gerado."
    }
@app.get("/posicoes")
def obter_posicoes_do_mapa(cliente_id: str = Depends(verificar_cracha)):
    """
    O parâmetro Depends(verificar_cracha) é o Poka-Yoke. 
    A rota só executa se o utilizador passar no leitor de crachás.
    """
    try:
        # 1. Abrir ligação à Base de Dados
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) # type: ignore
        query_api = client.query_api()

        # 2. Construir o Pedido (Query Flux) com Filtro Rigoroso Multi-Tenant
        # Pede os dados dos últimos 5 minutos, mas SÓ daquele tenant_id!
        query = f"""
            from(bucket: "{INFLUX_BUCKET}")
            |> range(start: -5m)
            |> filter(fn: (r) => r["_measurement"] == "utag_position")
            |> filter(fn: (r) => r["tenant_id"] == "{cliente_id}") 
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        """
        
        # 3. Executar o pedido
        tabelas = query_api.query(query)
        
        # 4. Transformar os dados complexos do Influx num formato simples para a WebApp
        posicoes = []
        for tabela in tabelas:
            for linha in tabela.records:
                posicoes.append({
                    "tag_id": linha.values.get("tag"),
                    "x": linha.values.get("x"),
                    "y": linha.values.get("y"),
                    "timestamp": linha.values.get("_time")
                })
                
        client.close()
        
        return {
            "cliente": cliente_id,
            "total_tags_detetadas": len(posicoes),
            "dados": posicoes
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no Armazém de Dados: {str(e)}")
    
@app.get("/app", tags=["Interface Gráfica"])
def servir_webapp():
# Quando alguém vai a /app, o servidor entrega-lhe o ficheiro HTML
    return FileResponse("frontend/index.html")