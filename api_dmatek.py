from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from influxdb_client import InfluxDBClient # type: ignore
from jose import jwt
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import math

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY", "chave-provisoria-para-teste")
ALGORITHM = "HS256" # O algoritmo matemático que "sela" o crachá

# 2. Inicializar o API
app = FastAPI(
    title="Portal de Dados RTLS",
    description="API de Gestão Multi-Tenant para posições em tempo real.",
    version="1.0.0"
)

# permite que o HTML encontre o app.js
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
async def read_root():
    return FileResponse("frontend/index.html")

@app.get("/relatorio.html")
async def read_relatorio():
    return FileResponse("frontend/relatorio.html")

# --- MVP: SIMULADOR DE UTILIZADORES E CLIENTES ---
# Na Fase 4, isto virá de uma base de dados real (ex: PostgreSQL)
UTILIZADORES = {
    "gestor_a": {"password": "123", "tenant_id": "cliente_A"}, 
    "gestor_b": {"password": "456", "tenant_id": "cliente_B"},
    "gestor_c": {"password": "789", "tenant_id": "cliente_C"},
    "gestor_d": {"password": "abc", "tenant_id": "cliente_A"}
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
        "tenant_id": id_do_cliente,
        "mensagem": f"Bem-vindo {credenciais.username}. O teu crachá foi gerado."
    }
@app.get("/posicoes")
def obter_posicoes_do_mapa(cliente_id: str = Depends(verificar_cracha)):
    """
    O parâmetro Depends(verificar_cracha) é o Poka-Yoke. 
    A rota só executa se o utilizador passar no leitor de crachás.
    """
    try:
        # 1. Abrir ligação à Base de Dados local para este pedido
        with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as influx_client:
            query_api = influx_client.query_api()

            # 2. Construir o Pedido (Query Flux) com Filtro Multi-Tenant
            query = f"""
                from(bucket: "{INFLUX_BUCKET}")
                |> range(start: -1h)
                |> filter(fn: (r) => r["_measurement"] == "posicao_tag")
                |> filter(fn: (r) => r["tenant_id"] == "{cliente_id}") 
                |> last()
                |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            """

            # 3. Executar o pedido
            tabelas = query_api.query(query)

        # 4. Transformar os dados complexos do Influx num formato simples para a WebApp
        posicoes = []
        for tabela in tabelas:
            for linha in tabela.records:
                x = linha.values.get("coord_x")
                y = linha.values.get("coord_y")
                if x is None or y is None:
                    continue

                status_val = linha.values.get("status")
                posicoes.append({
                    "tag_id": linha.values.get("tag_id"),
                    "x": x,
                    "y": y,
                    "timestamp": linha.values.get("_time"),
                    "bateria": linha.values.get("bateria") if linha.values.get("bateria") is not None else 0,
                    "status": status_val if status_val is not None else "Urgency"
                })

        return {
            "cliente": cliente_id,
            "total_tags_detetadas": len(posicoes),
            "dados": posicoes
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no Armazém de Dados: {str(e)}")

@app.get("/kpis/{tenant_id}")
async def obter_kpis_turno(tenant_id: str):
    # 1. A QUERY INFLUXDB puxa os últimos dados (8h), filtra pelo tenant, e faz pivot(X, o Y e a Bateria na mesma linha de tempo para facilitar as contas)
    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: -8h)
      |> filter(fn: (r) => r["_measurement"] == "posicao_tag")
      |> filter(fn: (r) => r["tenant_id"] == "{tenant_id}")
      |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
      |> group(columns: ["tag_id"])
      |> sort(columns: ["_time"])
    '''
    
    # 2. ESTRUTURAS DE DADOS PARA ARMAZENAR RESULTADOS
    frota_kpis = {
        "distancia_total_cm": 0,
        "leituras_em_movimento": 0,
        "leituras_totais": 0
    }
    
    tags_processadas = {}

    try:
        
        with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client_local:
            # Passamos explicitamente a organização e a query
            resultado = client_local.query_api().query(org=INFLUX_ORG, query=query)
        
        # 3. O MOTOR DE CÁLCULO
        for table in resultado:
            for record in table.records:
                tag_id = record.values.get("tag_id")
                x_atual = record.values.get("coord_x")
                y_atual = record.values.get("coord_y")
                bateria_atual = record.values.get("bateria")
                
                # Ignorar registos sem tag_id ou coordenadas
                if tag_id is None or x_atual is None or y_atual is None:
                    continue
                    
                frota_kpis["leituras_totais"] += 1
                
                # Registar a bateria (vai reescrevendo para ficar sempre com a mais recente no final do loop)
                if tag_id not in tags_processadas:
                    tags_processadas[tag_id] = {
                        "ultimo_x": None, "ultimo_y": None,
                        "bateria": 0, "distancia_cm": 0,
                        "leituras_totais": 0, "leituras_em_movimento": 0
                    }
                
                tags_processadas[tag_id]["leituras_totais"] += 1
                
                if bateria_atual is not None:
                    tags_processadas[tag_id]["bateria"] = bateria_atual
                
                # Calcular Distância e Movimento (se já houver um ponto anterior)
                ultimo_x = tags_processadas[tag_id]["ultimo_x"]
                ultimo_y = tags_processadas[tag_id]["ultimo_y"]
                
                if ultimo_x is not None and ultimo_y is not None:
                    # Fórmula da distância Euclidiana entre dois pontos consecutivos da mesma tag
                    distancia_ponto = math.sqrt((x_atual - ultimo_x)**2 + (y_atual - ultimo_y)**2)
                    
                    # Acumula na frota (para o KPI global) E na tag individual (para o gráfico)
                    frota_kpis["distancia_total_cm"] += distancia_ponto
                    tags_processadas[tag_id]["distancia_cm"] += distancia_ponto
                    
                    # Limiar de movimento produtivo (> 50 cm entre leituras)
                    if distancia_ponto > 50:
                        frota_kpis["leituras_em_movimento"] += 1
                        tags_processadas[tag_id]["leituras_em_movimento"] += 1
                
                # Atualizar o último ponto para o próximo ciclo
                tags_processadas[tag_id]["ultimo_x"] = x_atual
                tags_processadas[tag_id]["ultimo_y"] = y_atual

        # 4. CÁLCULOS FINAIS AGREGADOS
        distancia_total_metros = round(frota_kpis["distancia_total_cm"] / 100, 2)
        
        taxa_utilizacao = 0
        if frota_kpis["leituras_totais"] > 0:
            taxa_utilizacao = round((frota_kpis["leituras_em_movimento"] / frota_kpis["leituras_totais"]) * 100, 1)
            
        bateria_media = 0
        baterias_lista = [dados["bateria"] for dados in tags_processadas.values() if dados["bateria"] > 0]
        if len(baterias_lista) > 0:
            bateria_media = round(sum(baterias_lista) / len(baterias_lista), 1)

        grafico_distancias  = {}
        grafico_utilizacao  = {}
        grafico_bateria     = {}
        for tag, dados in tags_processadas.items():
            # Distância: acumulador individual convertido de cm para metros
            grafico_distancias[tag] = round(dados["distancia_cm"] / 100, 2)
            # Taxa de Utilização por tag: leituras em movimento / leituras totais * 100
            if dados["leituras_totais"] > 0:
                grafico_utilizacao[tag] = round(
                    (dados["leituras_em_movimento"] / dados["leituras_totais"]) * 100, 1
                )
            else:
                grafico_utilizacao[tag] = 0.0
            # Bateria: último valor registado para a tag
            grafico_bateria[tag] = round(dados["bateria"], 1)

        # 5. O OUTPUT
        return {
            "sucesso": True,
            "tenant_id": tenant_id,
            "kpis": {
                "distancia_percorrida_metros": distancia_total_metros,
                "taxa_utilizacao_perc": taxa_utilizacao,
                "bateria_media_frota_perc": bateria_media,
                "tags_ativas_turno": len(tags_processadas)
            },
            "grafico_distancias": grafico_distancias,
            "grafico_utilizacao": grafico_utilizacao,
            "grafico_bateria":    grafico_bateria
        }
        
    except Exception as e:
        return {"sucesso": False, "erro": str(e)}
   
@app.get("/app", tags=["Interface Gráfica"])
def servir_webapp():
# Quando alguém vai a /app, o servidor entrega-lhe o ficheiro HTML
    return FileResponse("frontend/index.html")