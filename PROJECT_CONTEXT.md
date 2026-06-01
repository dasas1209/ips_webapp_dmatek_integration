# Metric4 RTLS — Contexto do Projeto

Sistema de localização em tempo real (RTLS) **multi-tenant** por triangulação UWB indoor.
Stack: Python 3.11+ · FastAPI · InfluxDB Cloud · SQLite3 · HTML/JS/CSS

---

## Arquitetura geral

```
Servidor Dmatek (WebSocket ws://172.16.0.201:5002/TagPosition)
        │  {"id_fisico":"TAG001","status":"OK","x":100.5,"y":45.3,"rssi":-45,"bateria":85}
        ▼
worker/escuta_dmatek.py  ← motor de captura (processo separado)
  ├── posicao_tag        → InfluxDB  (coord_x/y, status, battery_percent, tag_id, tenant_id)
  └── evento_auditoria   → InfluxDB  (EMERGENCY_BUTTON, OFFLINE_ALARM, ONLINE_RECOVERY)
        │
        ▼
app/main.py (FastAPI/uvicorn :8000)
  ├── /app               → serve o frontend (index.html)
  ├── /token             → login OAuth2, devolve JWT
  ├── /posicoes          → última posição por tag  (polling 2s)
  ├── /historico         → snapshot num instante passado (slider temporal)
  ├── /kpis              → KPIs do turno atual
  ├── /relatorio/dados   → trajetória + KPIs + log de incidentes (auditoria)
  └── /admin/*           → CRUD de tenants, users, mapas, âncoras, tags
        │
        ▼
frontend/
  ├── index.html + app.js        → dashboard real-time (canvas + tabela)
  ├── relatorio.html + relatorio.js  → gráficos Chart.js de KPIs
  └── auditoria.html + auditoria.js  → trajetória esparguete + exportação PDF
```

---

## Ficheiros-chave

| Ficheiro | Responsabilidade |
|---|---|
| `config.py` | Lê `.env`, exporta constantes (INFLUX_*, SECRET_KEY, ALGORITHM, etc.) |
| `scripts/database_setup.py` | Cria tabelas SQLite + seed inicial (correr uma vez) |
| `worker/escuta_dmatek.py` | WebSocket listener → escrita InfluxDB (corre em janela separada) |
| `app/main.py` | FastAPI app principal — todos os endpoints REST + autenticação |
| `app/models.py` | Pydantic models (MapaCreate, UserCreate, etc.) |
| `app/dependencies.py` | JWT, rate limiting, dependências partilhadas |
| `app/routes/` | Endpoints por domínio (auth, realtime, kpis, admin, audit, tenant) |
| `app/services/database.py` | `get_db_connection`, `validar_tenant_id`, `carregar_matriz_clientes`, `obter_limites_mapa` |
| `app/services/influx_client.py` | Singleton do cliente InfluxDB (evita TCP/TLS por pedido) |
| `app/services/kpi_engine.py` | `calcular_kpis(RegistoTag) → KpiTag` — função pura sem I/O |
| `scripts/arrancar_sistema_v1.bat` | Arranque completo: pip install → DB setup → escuta → API → browser |

---

## Base de dados SQLite (`metric4rtls_system.db`)

### `clientes`
| col | tipo | constraints |
|---|---|---|
| `id` | TEXT | PRIMARY KEY |
| `nome` | TEXT | NOT NULL |
| `logo_url` | TEXT | — |
| `password` | TEXT | — |

### `users`
| col | tipo | constraints |
|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT |
| `username` | TEXT | NOT NULL UNIQUE |
| `password` | TEXT | NOT NULL |
| `cliente_id` | TEXT | NOT NULL → `clientes(id)` |

### `mapas`
| col | tipo | constraints |
|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT |
| `nome` | TEXT | NOT NULL |
| `limite_x` | REAL | NOT NULL |
| `limite_y` | REAL | NOT NULL |
| `ficheiro_dxf` | TEXT | — |
| `ficheiro_img` | TEXT | — |
| `cliente_id` | TEXT | NOT NULL → `clientes(id)` |

### `ancoras`
| col | tipo | constraints |
|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT |
| `id_fisico` | TEXT | NOT NULL |
| `mapa_id` | INTEGER | NOT NULL → `mapas(id)` |
| `coord_x` | REAL | NOT NULL |
| `coord_y` | REAL | NOT NULL |
| `coord_z` | REAL | NOT NULL DEFAULT 0.0 |

### `tags`
| col | tipo | constraints |
|---|---|---|
| `id_fisico` | TEXT | PRIMARY KEY |
| `nome` | TEXT | NOT NULL |
| `cliente_id` | TEXT | NOT NULL → `clientes(id)` |

---

## InfluxDB — Measurements

| Measurement | Fields | Tags |
|---|---|---|
| `posicao_tag` | status, coord_x, coord_y, battery_percent | tag_id, tenant_id |
| `evento_auditoria` | tipo, descricao | tag_id, tenant_id |

> Incidentes no relatório de auditoria provêm **exclusivamente** de `evento_auditoria`.
> O campo `status` de `posicao_tag` serve apenas para KPIs (utilização), nunca gera incidentes.

---

## Segurança e multi-tenancy

- **JWT** com `python-jose`: login em `/token` (OAuth2 password flow)
- **`require_tenant()`** dependency: injeta `tenant_id` do utilizador autenticado em todos os queries → isolamento de dados por tenant
- **Rate limiting**: 120 req/60s por tenant; 10 req/60s por username no login
- **Admin endpoints**: protegidos por role `admin`, CRUD completo com cascade delete

---

## Frontend

- `auth.js`: `obterToken`, `obterTenantId`, `redirecionarSeNaoAutenticado`, `tokenExpirado` — JWT em localStorage
- `app.js`: polling 2s a `/posicoes`, renderização canvas, tabela de assets, toasts de status
- `relatorio.js`: fetch `/kpis`, gráficos Chart.js (distância, utilização, bateria)
- `auditoria.js`: fetch `/relatorio/dados`, canvas esparguete de trajetória, exportação PNG/PDF (jsPDF)
- `runtime-config.js`: limites de mapa, timings e paths injetados em runtime (sem hardcode no JS)
- `asset-paths.js`: caminhos canónicos de imagens (`/static/assets/imgs/`, `imgs/maps/`, `imgs/avatars/`)

---

## Arranque

```bat
scripts\arrancar_sistema_v1.bat
```
Sequência: `pip install` → `scripts/database_setup.py` → `worker/escuta_dmatek.py` (janela separada) → `uvicorn app.main:app --reload` (janela separada) → browser em `http://127.0.0.1:8000/app`

---

## Contexto académico

Projeto PEGI (Projeto de Engenharia e Gestão Industrial) — FEUP, 3.º ano, 2.º semestre.
Empresa parceira: **Metric4**. O sistema é deployado numa fábrica real para tracking de assets industriais.
