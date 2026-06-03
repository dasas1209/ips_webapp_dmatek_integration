# Metric4 RTLS — Contexto do Projeto

Sistema de localização em tempo real (RTLS) **multi-tenant** por triangulação UWB indoor.  
Stack: Python 3.11+ · FastAPI · InfluxDB Cloud · SQLite3 · HTML/JS/CSS

---

## Arquitetura geral

```
Servidor Dmatek (WebSocket ws://<IP_SERVIDOR_DMATEK>:<PORTA_DMATEK>/TagPosition)
        │  pacote JSON: {TagID, PX, PY, NMTime, MType, Batt}
        ▼
worker/escuta_dmatek.py  ← processo separado (asyncio)
  ├── posicao_tag        → InfluxDB  (coord_x/y, status, nm_time, bateria, tag_id, tenant_id)
  └── evento_auditoria   → InfluxDB  (EMERGENCY_BUTTON, OFFLINE_ALARM, ONLINE_RECOVERY)
        │
        ▼
app/main.py (FastAPI/uvicorn :8000)
  ├── /app               → serve o frontend (index.html)
  ├── /login             → autenticação JWT (role: superadmin | admin | user)
  ├── /posicoes          → última posição por tag  (polling 2s)
  ├── /historico         → snapshot num instante passado (slider temporal)
  ├── /kpis              → KPIs do turno atual
  ├── /relatorio/dados   → trajetória + KPIs + log de incidentes (auditoria)
  ├── /api/tenant/*      → branding, perfil, avatar do tenant
  ├── /api/user/*        → credenciais do utilizador autenticado
  ├── /admin/audit-log   → log global de acções (superadmin)
  └── /api/admin/*       → CRUD completo (tenants, users, mapas, tags)
        │
        ▼
frontend/
  ├── index.html + app.js           → dashboard real-time (canvas + tabela)
  ├── relatorio.html + relatorio.js → gráficos Chart.js de KPIs
  ├── auditoria.html + auditoria.js → trajetória esparguete + exportação PNG/PDF
  ├── admin.html                    → painel de gestão Bootstrap (CRUD)
  └── audit_log.html + audit_log.js → log de acções superadmin + exportação PDF
```

---

## Ficheiros-chave

| Ficheiro | Responsabilidade |
|---|---|
| `config.py` | Lê `.env`, valida `SECRET_KEY`, exporta todas as constantes do sistema |
| `scripts/database_setup.py` | Cria tabelas SQLite + seed inicial (idempotente) |
| `worker/escuta_dmatek.py` | WebSocket listener → escrita InfluxDB + detecção offline/recovery (asyncio) |
| `app/main.py` | FastAPI app — CORS, mounts estáticos, startup hook |
| `app/models.py` | Pydantic models (MapaCreate, UserCreate, TenantCreate, etc.) |
| `app/dependencies.py` | JWT, rate limiting, roles, log de auditoria (TenantRateLimiter, log_audit_event) |
| `app/state.py` | Cache em memória de utilizadores lidos da BD (recarregada após alterações de admin) |
| `app/routes/auth.py` | `/login`, `/logout` — autenticação por users e por clientes |
| `app/routes/realtime.py` | `/posicoes`, `/historico` — dados em tempo real e histórico |
| `app/routes/kpis.py` | `/kpis`, `/relatorio/dados` — KPIs e dados de auditoria |
| `app/routes/admin.py` | `/api/admin/*` — CRUD de tenants, users, mapas, tags |
| `app/routes/audit.py` | `/admin/audit-log`, `/api/admin/*/sessions` — log de acções |
| `app/routes/tenant.py` | `/api/tenant/*`, `/api/user/credentials` — perfil e branding |
| `app/services/database.py` | `get_db_connection`, `validar_tenant_id`, `carregar_matriz_clientes`, `obter_limites_mapa` |
| `app/services/influx_client.py` | Singleton do cliente InfluxDB (evita TCP/TLS por pedido) |
| `app/services/kpi_engine.py` | `calcular_kpis(RegistoTag) → KpiTag` — função pura sem I/O |
| `scripts/arrancar_sistema_v1.bat` | Arranque completo: pip install → DB setup → escuta → API → browser |

---

## Frontend — módulos JavaScript

| Ficheiro | Responsabilidade |
|---|---|
| `auth.js` | JWT: `obterToken`, `obterTenantId`, `obterRole`, `obterNomeUtilizador`, `redirecionarSeNaoAutenticado` |
| `app.js` | Dashboard: login, polling `/posicoes`, canvas operacional, tabela de assets, toasts |
| `relatorio.js` | Fetch `/kpis`, renderização Chart.js (distância, utilização, bateria) |
| `auditoria.js` | Fetch `/relatorio/dados`, canvas esparguete de trajetória, exportação PNG/PDF |
| `audit_log.js` | Fetch `/admin/audit-log`, filtros, paginação, exportação PDF (superadmin) |
| `pdf-utils.js` | Utilitários PDF partilhados: carregamento de logo, inserção em PDF, rodapé numerado |
| `asset-paths.js` | Caminhos canónicos de imagens (`/static/assets/imgs/`), avatar fallback e iniciais |
| `runtime-config.js` | Configuração runtime injectada no browser (timings, raios canvas, paths API, temas) |

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
| `posicao_tag` | `coord_x, coord_y, nm_time, status, bateria` | `tag_id, tenant_id` |
| `evento_auditoria` | `descricao, coord_x, coord_y` | `tag_id, tenant_id, tipo` |
| `system_access_log` | `action, details` | `user_id, tenant_id` |

> Incidentes no relatório de auditoria provêm **exclusivamente** de `evento_auditoria`.
> O campo `status` de `posicao_tag` serve apenas para KPIs (utilização), nunca gera incidentes.

---

## Segurança e multi-tenancy

- **JWT** com `python-jose`: login em `/login` (OAuth2 password flow) — roles: `superadmin`, `admin`, `user`
- **`verificar_token()`** injecta `tenant_id` do JWT em todos os queries → isolamento por tenant
- **Rate limiting**: 120 req/60s por tenant (endpoints normais); 10 req/60s por username (login)
- **`require_admin()`** / **`require_superadmin()`**: protege endpoints admin com 403 se role insuficiente
- **`_verificar_acesso_tenant()`**: superadmin acede a todos os tenants; admin apenas ao seu próprio

---

## Ficheiros de configuração

| Ficheiro | Controla |
|---|---|
| `.env` | Credenciais e parâmetros de ambiente (não versionado) |
| `.env.example` | Template documentado de todos os parâmetros |
| `config.py` | Lê `.env`, valida `SECRET_KEY` e exporta constantes |
| `frontend/runtime-config.js` | Timings de polling, raios do canvas, paths de API, paleta de cores, temas por tenant |

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
