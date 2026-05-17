"""
LicitAttivos — Backend FastAPI
Esqueleto da aplicação. Nenhuma lógica de agente aqui — apenas rotas e lifecycle.
"""
import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from db.client import get_supabase_client
from routers import health, editais, products, pipeline
from fastapi import WebSocket, WebSocketDisconnect
from ws.manager import manager
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

# ── Observabilidade: Sentry (Caixa Preta do Avião) ──
SENTRY_DSN = settings.sentry_dsn
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[FastApiIntegration()],
        # Tracing de performance: útil para flagrar latência > 15s no Agente 3
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
    )

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown da aplicação."""
    log.info("licitattivos.starting", environment=settings.environment)

    # Valida conexão com Supabase no startup
    try:
        client = get_supabase_client()
        client.table("products").select("id").limit(1).execute()
        log.info("supabase.connected")
    except Exception as e:
        log.error("supabase.connection_failed", error=str(e))
        raise

    yield

    log.info("licitattivos.shutdown")


app = FastAPI(
    title="LicitAttivos API",
    description="Sistema multi-agente de automação de licitações — Attivos Magisttrais",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Next.js dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(editais.router, prefix="/api/editais", tags=["editais"])
app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])

@app.websocket("/ws/war-room")
async def websocket_war_room(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
            elif data.get("type") == "ack":
                manager.acknowledge_event(data.get("event_id"))
    except WebSocketDisconnect:
        manager.disconnect(websocket)
