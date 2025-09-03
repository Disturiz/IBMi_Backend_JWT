# backend/app/main.py
from dotenv import load_dotenv, find_dotenv, dotenv_values

load_dotenv(find_dotenv(usecwd=True), override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os, pathlib


# --- Lifespan: reemplaza on_event("startup") ---
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    # STARTUP
    envp = find_dotenv(usecwd=True)
    if not envp:
        raise RuntimeError(
            "No se encontró .env; ejecuta uvicorn desde la raíz del backend."
        )

    vals = dotenv_values(envp)
    # Completa variables que falten leyendo el .env (por si python-dotenv ignoró alguna)
    for k in ("JT400_JAR", "IBMI_JDBC_URL", "IBMI_USER", "IBMI_PASSWORD"):
        if not (os.getenv(k) or "").strip():
            v = vals.get(k)
            if v:
                os.environ[k] = str(v)

    # Validaciones duras
    missing = [
        k
        for k in ("JT400_JAR", "IBMI_JDBC_URL", "IBMI_USER", "IBMI_PASSWORD")
        if not (os.getenv(k) or "").strip()
    ]
    if missing:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")

    jar = os.getenv("JT400_JAR")
    if not pathlib.Path(jar).is_file():
        raise RuntimeError(f"jt400.jar no existe en: {jar}")

    yield  # --- aquí la app ya corre ---

    # SHUTDOWN (si necesitas cerrar pools/conexiones, hazlo aquí)
    # p.ej. cerrar clientes, etc.


app = FastAPI(title="IBMi Backend API", version="1.0.0", lifespan=app_lifespan)

# CORS (útil si a veces llamas directo, sin proxy de Vite)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from .auth import router as auth_router
from .routes.etl import router as etl_router
from .routes.legacy import router as legacy_router

app.include_router(auth_router)  # -> /login
app.include_router(etl_router, prefix="/etl")  # -> /etl/...
app.include_router(legacy_router)  # -> /health, /catalog/*, /extract


# Debug (lo obtenemos del módulo ibmi cuando se llame)
@app.get("/debug/env")
def debug_env():
    from .services import ibmi

    return ibmi.debug_info()


# Ejecutar como script (opcional; normalmente usa CLI)
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8020")), reload=True)
