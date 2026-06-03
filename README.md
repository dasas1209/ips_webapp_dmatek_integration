# Metric4 RTLS — Documentação do Projecto

Sistema de localização em tempo real (RTLS) multi-tenant por triangulação UWB indoor.  
Stack: Python 3.11+ · FastAPI · InfluxDB Cloud · SQLite3 · HTML/JS/CSS

---

## Estrutura de Ficheiros

```
06_Motor_Captura/
│
├── .env                         # variáveis de ambiente (não versionado — copiar de .env.example)
├── .env.example                 # template com todos os parâmetros documentados
├── .gitignore
├── requirements.txt             # dependências Python
│
│   ── CONFIGURAÇÃO ──
│
├── config.py                    # configuração centralizada — lê .env e exporta constantes
│
│   ── WORKER ──
│
├── worker/
│   └── escuta_dmatek.py         # motor WebSocket: recebe posições do Dmatek → grava no InfluxDB
│
│   ── SCRIPTS ──
│
├── scripts/
│   ├── database_setup.py        # inicialização e seeding da BD SQLite (correr uma vez)
│   └── arrancar_sistema_v1.bat  # arranque completo Windows (pip install → setup → escuta → API → browser)
│
│   ── API ──
│
├── app/
│   ├── main.py                  # FastAPI app, CORS, mounts, startup hook
│   ├── models.py                # Pydantic models (MapaCreate, UserCreate, TenantCreate, etc.)
│   ├── dependencies.py          # JWT, rate limiting, roles, log de auditoria partilhados
│   ├── state.py                 # estado global em memória (cache de utilizadores da BD)
│   ├── routes/
│   │   ├── auth.py              # /login, /logout
│   │   ├── realtime.py          # /posicoes, /historico
│   │   ├── kpis.py              # /kpis, /relatorio/dados
│   │   ├── admin.py             # /api/admin/* (CRUD tenants, users, mapas, tags)
│   │   ├── audit.py             # /admin/audit-log, /api/admin/*/sessions
│   │   └── tenant.py            # /api/tenant/* (branding, perfil, avatar), /api/user/credentials
│   └── services/
│       ├── database.py          # get_db_connection · validar_tenant_id · carregar_matriz_clientes · obter_limites_mapa
│       ├── influx_client.py     # singleton do cliente InfluxDB (evita abertura de ligação TCP por pedido)
│       └── kpi_engine.py        # cálculo de KPIs por tag — função pura sem I/O (RegistoTag · KpiTag · calcular_kpis)
│
│   ── BASE DE DADOS ──
│
├── metric4rtls_system.db        # BD SQLite gerada pelo database_setup.py (não versionada)
│
│   ── FRONTEND ──
│
└── frontend/
    ├── index.html               # dashboard principal (login + mapa operacional em tempo real)
    ├── relatorio.html           # relatórios de KPI por tag (Chart.js)
    ├── auditoria.html           # auditoria: esparguete · incidentes · exportação PNG/PDF
    ├── admin.html               # painel de gestão (Bootstrap): CRUD tenants, users, mapas, tags
    ├── audit_log.html           # log global de acções (superadmin): filtros + exportação PDF
    ├── style.css                # estilos globais partilhados pelas 5 páginas
    ├── runtime-config.js        # configuração runtime injectada no browser (timings, paths de API, temas)
    ├── auth.js                  # JWT: obterToken · obterTenantId · obterRole · obterNomeUtilizador · redirecionarSeNaoAutenticado
    ├── app.js                   # lógica do dashboard: login · polling /posicoes · canvas · tabela · toasts
    ├── relatorio.js             # fetch /kpis · renderização Chart.js
    ├── auditoria.js             # fetch /relatorio/dados · esparguete canvas · exportação PNG/PDF
    ├── audit_log.js             # fetch /admin/audit-log · filtros · paginação · exportação PDF
    ├── pdf-utils.js             # utilitários PDF partilhados: logo, capa, rodapé (usado por auditoria.js e audit_log.js)
    ├── asset-paths.js           # caminhos canónicos de imagens e utilitários de avatar
    └── assets/
        └── imgs/
            ├── metric-logo.svg        # logotipo Metric4
            ├── maps/                  # plantas por cliente (ex: mapa_cliente_A.png)
            └── avatars/               # avatares de tenant (gerados em upload, não versionados)
```

---

## Dependências Python (`requirements.txt`)

| Pacote | Versão | Função |
|---|---|---|
| `fastapi` | ≥ 0.111, < 1.0 | Framework HTTP assíncrono (API REST) |
| `uvicorn[standard]` | ≥ 0.29, < 1.0 | Servidor ASGI para FastAPI |
| `influxdb-client` | ≥ 1.43, < 2.0 | Cliente InfluxDB Cloud (leitura e escrita de séries temporais) |
| `python-jose[cryptography]` | ≥ 3.3, < 4.0 | Geração e validação de tokens JWT |
| `websockets` | ≥ 12.0, < 14.0 | Ligação WebSocket ao servidor Dmatek |
| `python-dotenv` | ≥ 1.0, < 2.0 | Carregamento do ficheiro `.env` |
| `python-multipart` | ≥ 0.0.9, < 1.0 | Parsing de formulários OAuth2 no login |

**Dependências de frontend (CDN — sem instalação local):**

| Biblioteca | Versão | Função |
|---|---|---|
| Bootstrap | 5.3.2 | Estilos e componentes do painel admin (`admin.html`) |
| Chart.js | latest | Gráficos de barras em `relatorio.js` |
| jsPDF | 2.5.1 | Exportação PDF em `auditoria.js` e `audit_log.js` |
| FontAwesome | 6.4.2 | Ícones no painel admin |
| Google Fonts (Inter) | — | Tipografia global |

---

## Configuração (`.env`)

Copiar `.env.example` para `.env` e preencher os valores reais.  
O ficheiro `.env.example` está documentado com todos os parâmetros e os seus defaults.

```env
# obrigatorio
INFLUX_URL=https://<regiao>.aws.cloud2.influxdata.com/
INFLUX_TOKEN=<token-de-leitura-e-escrita>
INFLUX_ORG=<email-ou-org-id>
INFLUX_BUCKET=<nome-do-bucket>
SECRET_KEY=<chave-aleatoria-minimo-32-caracteres>

# servidor dmatek (obrigatorio em producao)
IP_SERVIDOR_DMATEK=172.16.0.201
PORTA_DMATEK=5002

# opcional — defaults razoaveis para desenvolvimento
TOKEN_EXPIRY_HOURS=2
ADMIN_TENANT_ID=cliente_admin
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin           # alterar em producao
CORS_ORIGINS=http://localhost:8000,https://rtls.metric4.pt
JANELA_KPI_HORAS=8
LIMITE_DIAS_HISTORICO=30
MATRIZ_RELOAD_INTERVAL_SEG=300
MAX_AVATAR_BYTES=2097152
AUDIT_LOG_INFLUX_LIMIT=10000
SESSIONS_LOG_LIMIT=500
API_BUILD_ID=dev
```

Ver `.env.example` para descrição completa de cada parâmetro.

---

## Schema da Base de Dados SQLite

| Tabela | Campos principais | Função |
|---|---|---|
| `clientes` | `id, nome, logo_url, password` | Tenants registados |
| `users` | `username, password, cliente_id` | Utilizadores por tenant |
| `mapas` | `nome, limite_x, limite_y, ficheiro_img, cliente_id` | Plantas por tenant |
| `ancoras` | `id_fisico, mapa_id, coord_x/y/z` | Âncoras UWB |
| `tags` | `id_fisico, nome, cliente_id` | Tags RTLS por tenant |

---

## Arranque

```bat
scripts\arrancar_sistema_v1.bat
```

O script faz, por ordem:
1. `pip install -r requirements.txt`
2. `python scripts/database_setup.py` — cria tabelas e seed inicial (idempotente)
3. `python worker/escuta_dmatek.py` — motor WebSocket (janela separada)
4. `uvicorn app.main:app --reload` — API REST (janela separada)
5. Abre `http://127.0.0.1:8000/app` no browser

**Arranque manual (desenvolvimento):**
```bat
pip install -r requirements.txt
python scripts/database_setup.py
start python worker/escuta_dmatek.py
uvicorn app.main:app --reload
```

---

## Arquitectura

```
Servidor Dmatek (WebSocket ws://<IP>:<PORTA>/TagPosition)
        │
        ▼
worker/escuta_dmatek.py
  ├── posicao_tag      → InfluxDB  (coord_x/y, status, bateria, tag_id, tenant_id)
  └── evento_auditoria → InfluxDB  (EMERGENCY_BUTTON, OFFLINE_ALARM, ONLINE_RECOVERY)
        │
        ▼
app/main.py (FastAPI / uvicorn :8000)
  │
  ├── POST /login              → JWT (role: superadmin | admin | user)
  ├── POST /logout
  │
  ├── GET  /posicoes           → última posição por tag  (polling 2s)
  ├── GET  /historico          → snapshot num instante passado (slider temporal)
  ├── GET  /kpis               → KPIs do turno actual (distância, utilização, bateria)
  ├── GET  /relatorio/dados    → trajetória + KPIs + log de incidentes
  │
  ├── GET  /api/mapas          → mapas do tenant autenticado
  ├── GET  /api/tenant/branding
  ├── PUT  /api/tenant/profile
  ├── POST /api/tenant/profile/avatar
  ├── PUT  /api/user/credentials
  │
  ├── GET  /admin/audit-log    → log global de acções (superadmin)
  │
  └── /api/admin/*             → CRUD completo (superadmin/admin)
        ├── tenants, users, mapas, tags, ancoras
        └── /api/admin/*/sessions  → histórico de sessões por tenant
        │
        ▼
frontend/
  ├── app.js        → dashboard (canvas + tabela, polling /posicoes)
  ├── relatorio.js  → gráficos Chart.js de KPIs
  ├── auditoria.js  → esparguete + exportação PNG/PDF
  └── audit_log.js  → log de acções superadmin + exportação PDF
```

**Measurements InfluxDB:**

| Measurement | Fields | Tags |
|---|---|---|
| `posicao_tag` | `coord_x, coord_y, status, nm_time, bateria` | `tag_id, tenant_id` |
| `evento_auditoria` | `descricao, coord_x, coord_y` | `tag_id, tenant_id, tipo` |
| `system_access_log` | `action, details` | `user_id, tenant_id` |

> **Nota:** Os incidentes no relatório de auditoria provêm **exclusivamente** da measurement
> `evento_auditoria`. O campo `status` de `posicao_tag` é usado apenas para KPIs (utilização),
> nunca gera entradas no log de incidentes — evita duplicação.

---

## Ficheiros de configuração

| Ficheiro | Controla |
|---|---|
| `.env` | Credenciais e parâmetros de ambiente (não versionado) |
| `.env.example` | Template documentado de todos os parâmetros |
| `config.py` | Lê `.env`, valida SECRET_KEY e exporta todas as constantes do sistema |
| `frontend/runtime-config.js` | Configuração runtime do browser: timings de polling, raios do canvas, paths de API, temas por tenant |
