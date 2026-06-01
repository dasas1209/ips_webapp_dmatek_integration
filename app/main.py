"""
app/main.py
entry point da api fastapi do sistema metric4 rtls
arranque: uvicorn app.main:app --reload
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import ALLOWED_ORIGINS, API_BUILD_ID
from app import state
from app.routes import auth, realtime, kpis, admin, audit, tenant

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("metric4.api")

_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}

app = FastAPI(
    title="Portal de Dados RTLS — Metric4",
    description="API de Gestao Multi-Tenant para posicoes em tempo real.",
    version="2.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.mount("/static", StaticFiles(directory="frontend"), name="static")

# routers
app.include_router(auth.router)
app.include_router(realtime.router)
app.include_router(kpis.router)
app.include_router(admin.router)
app.include_router(audit.router)
app.include_router(tenant.router)


@app.on_event("startup")
async def _startup() -> None:
    state.reload_utilizadores()
    tenant_routes = sorted(
        r.path for r in app.routes
        if hasattr(r, "path") and isinstance(r.path, str) and r.path.startswith("/api/tenant/")
    )
    logger.info("API build %s | rotas tenant: %s", API_BUILD_ID, tenant_routes)


@app.get("/api/health", include_in_schema=False)
def api_health():
    return {"ok": True, "build": API_BUILD_ID, "tenant_profile_api": True}


# serving de paginas html

@app.get("/", include_in_schema=False)
@app.get("/app", include_in_schema=False)
async def serve_index():
    return FileResponse("frontend/index.html", headers=_NO_CACHE)


@app.get("/relatorio.html", include_in_schema=False)
async def serve_relatorio():
    return FileResponse("frontend/relatorio.html", headers=_NO_CACHE)


@app.get("/auditoria.html", include_in_schema=False)
async def serve_auditoria():
    return FileResponse("frontend/auditoria.html", headers=_NO_CACHE)


@app.get("/admin.html", include_in_schema=False)
async def serve_admin():
    return FileResponse("frontend/admin.html", headers=_NO_CACHE)


@app.get("/app/audit-log", include_in_schema=False)
async def serve_audit_log():
    return FileResponse("frontend/audit_log.html", headers=_NO_CACHE)
