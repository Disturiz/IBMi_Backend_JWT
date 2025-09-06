# backend/app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv, find_dotenv
import os, pathlib


# --- Lifespan: carga .env y valida prerequisitos ----------------------------
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    # Cargar .env desde la raíz del backend (donde ejecutas uvicorn)
    env_path = find_dotenv(usecwd=True)  # busca ".env" hacia arriba desde cwd
    if env_path:
        load_dotenv(env_path, override=False)

    # Validaciones duras (ajusta los nombres si tu servicio usa otros)
    required = ("JT400_JAR", "IBMI_JDBC_URL", "IBMI_USER", "IBMI_PASSWORD")
    missing = [k for k in required if not (os.getenv(k) or "").strip()]
    if missing:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")

    jar = os.getenv("JT400_JAR")
    if not pathlib.Path(jar).is_file():
        raise RuntimeError(f"jt400.jar no existe en: {jar}")

    yield  # --- la app ya corre aquí ---
    # (opcional) cerrar pools/conexiones en shutdown


# --- App --------------------------------------------------------------------
app = FastAPI(title="IBMi Backend API", version="1.0.0", lifespan=app_lifespan)

# CORS (frontend Vite en :5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ----------------------------------------------------------------
# /login
from .auth import router as auth_router

# /etl/*
from .routes.etl import router as etl_router

# /health/n8n (tu router nuevo)
from .routes.health_n8n import router as health_n8n_router

# /health, /catalog/*, /extract (si existe en tu repo)
try:
    from .routes.legacy import router as legacy_router
except Exception:
    legacy_router = None  # por si ese módulo no existe en tu copia

app.include_router(auth_router)  # -> /login
app.include_router(etl_router, prefix="/etl")  # -> /etl/...
app.include_router(health_n8n_router)  # -> /health/n8n
if legacy_router:
    app.include_router(legacy_router)


# Debug opcional
@app.get("/debug/env")
def debug_env():
    from .services import ibmi

    return ibmi.debug_info()


# Ejecutar como script (normalmente usar uvicorn CLI)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8020")), reload=True)
