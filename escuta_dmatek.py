import asyncio
import websockets
import json
import time

# para registo de eventos críticos em csv
import csv
from datetime import datetime  

# ----------------------------
# para registo de dados em InfluxDB (py vai buscar valores ao .env e guarda-os na memória)
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
import os
from dotenv import load_dotenv

load_dotenv()

INFLUX_URL = os.getenv("INFLUX_URL")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN")
INFLUX_ORG = os.getenv("INFLUX_ORG")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET")

# Inicializar o motor da Base de Dados
client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = client.write_api(write_options=SYNCHRONOUS)

# ------------------------------------
# CONFIGURAÇÕES PARA ESCALABILIDADE 
# Setup do Cliente
IP_SERVIDOR = "172.16.0.201"
PORTA = "5002"
ENDPOINT = "/TagPosition" 
# Dimensões reais do mapa no cliente (em centímetros) - não corrige erros para áreas em L ou com formas não retangulares 
LIMITE_X_CM = 760
LIMITE_Y_CM = 500
# Lógica de Inteligent Power Strategy (Tempos em Segundos)
TIMEOUT_MOVIMENTO = 1 # se mexe, tem de reportar neste intervalo em segundos
TIMEOUT_REPOUSO = 70 # se parada (NMTime > 0), damos este intervalo de tolerância em segundos para reportar antes de considerar offline
# Se o Static Locate Interval no Set.exe > TIMEOUT_REPOUSO -> alarmes falsos de "Offline"
# Tabela de Tags em Memória
# Estrutura: { "tagID": {"timestamp": 0.0, "status": "online"} }
registo_de_tags = {}
# Motor para Multi-Tenant
def carregar_matriz_clientes(ficheiro="matriz_clientes.csv"):
    matriz = {}
    
    # se o ficheiro não existir, avisa em vez de crashar
    if not os.path.exists(ficheiro):
        print(f"[AVISO] Ficheiro {ficheiro} não encontrado. A operar sem identificação de clientes.")
        return matriz
    
    try:
        with open(ficheiro, mode='r', encoding='utf-8') as file:
            # Usa a primeira linha como nomes das colunas
            reader = csv.DictReader(file, delimiter=';')
            for linha in reader:
                # O .strip() limpa espaços em branco acidentais
                tag = linha.get('tag_id', '').strip()
                tenant = linha.get('tenant_id', '').strip()
                
                # Só adiciona se a linha estiver bem preenchida
                if tag and tenant:
                    matriz[tag] = tenant
                    
        print(f"Matriz Dinâmica Carregada: {len(matriz)} tags mapeadas a partir do CSV.")
    except Exception as e:
        print(f"❌ Erro ao ler a Matriz de Clientes: {e}")
        
    return matriz

# Carrega a tabela para a memória quando o script arranca
MATRIZ_CLIENTES = carregar_matriz_clientes()
# ------------------------------------

def registar_evento(tag_id, evento, detalhes):
    # Escreve uma linha no ficheiro CSV sempre que algo crítico acontece
    hora_atual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ficheiro_csv = "auditoria_tags.csv"
    
    with open(ficheiro_csv, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file, delimiter=';')
        writer.writerow([hora_atual, tag_id, evento, detalhes])

async def monitorizar_saude():
    # Tarefa paralela que verifica quem 'morreu' na rede
    while True:
        agora = time.time()
        for tag_id, info in registo_de_tags.items():
            tempo_sem_sinal = agora - info['timestamp']
            
            # Escolhe o limite baseado no estado que a tag reportou da última vez
            limite = TIMEOUT_REPOUSO if info['em_repouso'] else TIMEOUT_MOVIMENTO
            
            if tempo_sem_sinal > limite and info['status'] == "online":
                info['status'] = "offline"
                msg_alerta = f"Sem sinal há {tempo_sem_sinal:.1f}s"
                print(f"[ALERTA] Tag {tag_id} ficou OFFLINE! ({msg_alerta})")
                # Regista o evento no CSV
                registar_evento(tag_id, "OFFLINE_ALARM", msg_alerta)
        
        await asyncio.sleep(2) # Verifica a saúde a cada 2 segundos


async def escutar_fabrica():
    URI = f"ws://{IP_SERVIDOR}:{PORTA}{ENDPOINT}"
    print(f"Válvula de dados aberta em: {URI}")
    
    try:
        async with websockets.connect(URI) as websocket:
            while True:
                dados_brutos = await websocket.recv()
                agora = time.time()
                
                try:
                    pacote = json.loads(dados_brutos)
                    lista_de_tags = pacote if isinstance(pacote, list) else [pacote]

                    for tag in lista_de_tags:
                        tag_id = tag.get("TagID", "Desconhecida")
                        px = tag.get("PX", -1)
                        py = tag.get("PY", -1)
                        nm_time = tag.get("NMTime", 0) # Tempo parada

                        # 1. POKA-YOKE
                        if not (0 <= px <= LIMITE_X_CM and 0 <= py <= LIMITE_Y_CM):
                            print(f"❌ [Tag {tag_id}] Fora do Mapa. Ignorada.")
                            continue

                        # 2. ATUALIZAR INVENTÁRIO (Lógica de Estado)
                        estava_offline = registo_de_tags.get(tag_id, {}).get("status") == "offline"
                        
                        registo_de_tags[tag_id] = {
                            "timestamp": agora,
                            "em_repouso": nm_time > 0,
                            "status": "online"
                        }

                        if estava_offline:
                            print(f"✅ [Tag {tag_id}] VOLTOU A ESTAR ONLINE!")
                            # Gravar no ficheiro CSV
                            registar_evento(tag_id, "ONLINE_RECOVERY", "A tag voltou a comunicar com a rede.")

                        # Log de monitorização simples
                        modo = "REPOUSO" if nm_time > 0 else "MOVIMENTO"

                        # --- LÓGICA MULTI-TENANT ---
                        # O .get() procura a tag na matriz. Se não encontrar, assume "cliente_desconhecido" (Poka-yoke de software)
                        id_do_cliente = MATRIZ_CLIENTES.get(tag_id, "cliente_desconhecido")
                        # Criamos um Point - linha no Excel do Influx
                        ponto_bd = Point("posicao_tag") \
                            .tag("tag_id", tag_id) \
                            .tag("tenant_id", id_do_cliente) \
                            .field("coord_x", px) \
                            .field("coord_y", py) \
                            .field("nm_time", nm_time)
                        
                        # Escreve no influxdb
                        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=ponto_bd)
                        print(f"📍 [Tag {tag_id} -> {id_do_cliente}] {modo} | X:{px} Y:{py} | NMTime:{nm_time}s")

                except Exception as e:
                    print(f"Erro ao processar pacote: {e}")
                    
    except Exception as e:
        print(f"❌ Erro de ligação: {e}")

async def main():
    # Corre a escuta e a monitorização de saúde ao mesmo tempo
    await asyncio.gather(escutar_fabrica(), monitorizar_saude())

if __name__ == "__main__":
    asyncio.run(main())
