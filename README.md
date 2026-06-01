# Metric4 RTLS — Documentação do Projecto

Sistema de localização em tempo real (RTLS) multi-tenant.
Stack: Python 3.11+ · FastAPI · InfluxDB Cloud · SQLite3 · HTML/JS/CSS

---

## Estrutura de Ficheiros

```
06_Motor_Captura/
│
├── .env                        # variáveis de ambiente (não versionado — ver secção Configuração)
├── .gitignore
├── requirements.txt            # dependências Python
├── arrancar_sistema_v1.bat     # script de arranque Windows (instala deps, setup BD, inicia serviços)
│
│   ── BACKEND ──
│
├── config.py                   # configuração centralizada — lê .env e exporta constantes
├── database_setup.py           # inicialização e seeding da BD SQLite (correr uma vez)
├── escuta_dmatek.py            # motor WebSocket: recebe posições do servidor Dmatek → grava no InfluxDB
├── api_dmatek.py               # API REST FastAPI: autenticação JWT, endpoints de posições/KPIs/auditoria
├── shared.py                   # shim de compatibilidade — re-exporta de services/database.py
│
│   ── SERVIÇOS (lógica partilhada) ──
│
├── services/
│   ├── __init__.py
│   ├── database.py             # get_db_connection · validar_tenant_id · carregar_matriz_clientes · obter_limites_mapa
│   ├── influx_client.py        # singleton do cliente InfluxDB (evita abertura de ligação TCP por pedido)
│   └── kpi_engine.py           # cálculo de KPIs por tag — função pura sem I/O (RegistoTag · KpiTag · calcular_kpis)
│
│   ── BASE DE DADOS ──
│
├── metric4rtls_system.db       # BD SQLite gerada pelo database_setup.py (não versionada)
│
│   ── FRONTEND ──
│
└── frontend/
    ├── index.html              # dashboard principal (mapa operacional em tempo real)
    ├── relatorio.html          # página de relatórios de KPI por tag
    ├── auditoria.html          # página de auditoria (esparguete · KPIs · log de incidentes · exportação PDF)
    ├── style.css               # estilos globais partilhados pelas 3 páginas
    ├── runtime-config.js       # configuração runtime injectada no browser (limites de mapa, timings, CORS paths)
    ├── auth.js                 # JWT: obterToken · obterTenantId · redirecionarSeNaoAutenticado · tokenExpirado
    ├── app.js                  # lógica do dashboard: login · polling /posicoes · canvas · tabela · toasts
    ├── relatorio.js            # lógica dos relatórios: fetch /kpis · renderização Chart.js
    ├── auditoria.js            # lógica da auditoria: fetch /relatorio/dados · esparguete canvas · exportação PNG/PDF
    └── assets/
        └── imgs/
            ├── metric-logo.svg       # logotipo Metric4
            ├── maps/                 # plantas por cliente (ex: mapa_cliente_A.png)
            └── avatars/              # avatares de tenant/utilizador (opcional)
```

---

## Dependências Python (`requirements.txt`)

| Pacote | Versão | Função |
|---|---|---|
| `fastapi` | ≥ 0.111, < 1.0 | Framework HTTP assíncrono (API REST) |
| `uvicorn[standard]` | ≥ 0.29, < 1.0 | Servidor ASGI para FastAPI |
| `influxdb-client` | ≥ 1.43, < 2.0 | Cliente InfluxDB Cloud (leitura e escrita) |
| `python-jose[cryptography]` | ≥ 3.3, < 4.0 | Geração e validação de tokens JWT |
| `websockets` | ≥ 12.0, < 13.0 | Ligação WebSocket ao servidor Dmatek |
| `python-dotenv` | ≥ 1.0, < 2.0 | Carregamento do ficheiro `.env` |
| `python-multipart` | ≥ 0.0.9, < 1.0 | Parsing de formulários OAuth2 no login |

**Dependências de frontend (CDN — sem instalação local):**

| Biblioteca | Versão | Função |
|---|---|---|
| Chart.js | latest | Gráficos de barras em `relatorio.js` |
| jsPDF | 2.5.1 | Exportação PDF em `auditoria.js` |
| Google Fonts (Inter) | — | Tipografia |

---

## Configuração (`.env`)

```env
INFLUX_URL=https://<region>.aws.cloud2.influxdata.com/
INFLUX_TOKEN=<token-de-leitura-e-escrita>
INFLUX_ORG=<email-ou-org-id>
INFLUX_BUCKET=<nome-do-bucket>

SECRET_KEY=<chave-secreta-para-assinar-jwt>

# opcional — origens permitidas para CORS (separadas por vírgula)
# CORS_ORIGINS=http://localhost:8000,https://rtls.metric4.pt
```

---

## Schema da Base de Dados SQLite

| Tabela | Campos principais | Função |
|---|---|---|
| `clientes` | `id, nome, logo_url` | Tenants registados |
| `users` | `username, password, cliente_id` | Utilizadores por tenant |
| `mapas` | `nome, limite_x, limite_y, ficheiro_img, cliente_id` | Plantas por tenant |
| `ancoras` | `id_fisico, mapa_id, coord_x/y/z` | Âncoras UWB |
| `tags` | `id_fisico, nome, cliente_id` | Tags RTLS por tenant |

---

## Arranque

```bat
arrancar_sistema_v1.bat
```

O script faz, por ordem:
1. `pip install -r requirements.txt`
2. `python database_setup.py` — cria tabelas e seed inicial
3. `python escuta_dmatek.py` — motor WebSocket (janela separada)
4. `uvicorn api_dmatek:app --reload` — API REST (janela separada)
5. Abre `http://127.0.0.1:8000/app` no browser

---

## Arquitectura de dados em tempo real

```
Servidor Dmatek (WebSocket)
        │
        ▼
escuta_dmatek.py
  ├── grava posicao_tag → InfluxDB  (campo status, coord_x/y, bateria, tenant_id)
  └── grava evento_auditoria → InfluxDB  (EMERGENCY_BUTTON, OFFLINE_ALARM, ONLINE_RECOVERY)
        │
        ▼
api_dmatek.py (FastAPI)
  ├── GET /posicoes       → última posição por tag (polling 2s do frontend)
  ├── GET /historico      → posições num instante passado (slider temporal)
  ├── GET /kpis           → KPIs do turno actual (distância, utilização, bateria)
  └── GET /relatorio/dados → trajetória + KPIs + log de incidentes (auditoria)
        │
        ▼
frontend/
  ├── app.js       → dashboard em tempo real (canvas + tabela)
  ├── relatorio.js → gráficos Chart.js de KPIs
  └── auditoria.js → esparguete + PDF export
```

> **Nota:** Os incidentes no relatório de auditoria provêm **exclusivamente** da measurement
> `evento_auditoria`. O campo `status` da measurement `posicao_tag` é usado apenas para
> calcular KPIs (utilização) e não gera entradas no log de incidentes, evitando duplicação.
