import os
from contextlib import asynccontextmanager
from typing import Dict, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.core.cloud_config import CloudHealthService
from app.api.routes_projects import router as projects_router
from app.api.routes_scans import router as scans_router
from app.api.routes_generate import router as generate_router
from app.api.routes_export import router as export_router

# WebSocket Connection Manager for Real-time Multi-Agent Log Streaming
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, generation_id: str, websocket: WebSocket):
        await websocket.accept()
        if generation_id not in self.active_connections:
            self.active_connections[generation_id] = []
        self.active_connections[generation_id].append(websocket)

    def disconnect(self, generation_id: str, websocket: WebSocket):
        if generation_id in self.active_connections:
            self.active_connections[generation_id].remove(websocket)
            if not self.active_connections[generation_id]:
                del self.active_connections[generation_id]

    async def broadcast_to_generation(self, generation_id: str, message: dict):
        if generation_id in self.active_connections:
            for connection in self.active_connections[generation_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

ws_manager = ConnectionManager()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB tables on startup
    await init_db()
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Multi-Axis Vision to Parametric B-Rep CAD Platform",
    lifespan=lifespan
)

# CORS Middleware (Enable for frontend dev server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount storage directory for static access (uploaded images, edge maps, STL files)
app.mount("/storage", StaticFiles(directory=str(settings.STORAGE_DIR)), name="storage")

# Include API Routers
app.include_router(projects_router, prefix=settings.API_V1_PREFIX)
app.include_router(scans_router, prefix=settings.API_V1_PREFIX)
app.include_router(generate_router, prefix=settings.API_V1_PREFIX)
app.include_router(export_router, prefix=settings.API_V1_PREFIX)

@app.websocket("/ws/agent-logs/{generation_id}")
async def websocket_agent_logs(websocket: WebSocket, generation_id: str):
    await ws_manager.connect(generation_id, websocket)
    try:
        while True:
            # Keep socket alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(generation_id, websocket)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION
    }

@app.get("/health/cloud")
@app.get(f"{settings.API_V1_PREFIX}/health/cloud")
async def cloud_health_diagnostics():
    """Returns connection diagnostics across the 4 managed cloud tiers."""
    return await CloudHealthService.get_full_diagnostics()
