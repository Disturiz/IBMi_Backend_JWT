# backend/app/main.py
from pathlib import Path
from dotenv import load_dotenv
import os

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH, override=True)  # ← IMPORTANTE

print("Leyendo .env de:", ENV_PATH)
print("DBG PG_USER:", os.getenv("PG_USER"))
print("DBG PG_HOST:", os.getenv("PG_HOST"))


import os, io, re, time, datetime as dt
from pathlib import Path
from dotenv import load_dotenv

# Cargar el .env de la carpeta backend/
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)
print("Leyendo .env de:", ENV_PATH)
print(
    "DBG PG_USER:", os.getenv("PG_USER")
)  # debe imprimir postgres.oupiyzlmfpozatxsfgve
print(
    "DBG PG_HOST:", os.getenv("PG_HOST")
)  # debe imprimir aws-1-us-east-2.pooler.supabase.com

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import pandas as pd
import jaydebeapi
import jwt  # PyJWT


app = FastAPI(title="IBMi Extract API — JWT + Autocomplete")

origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
# from app.routes.kpis import router as kpis_router
from .routes import auth as auth_router

# from .routes import kpis as kpis_router
from .routes import catalog as catalog_router
from .routes import etl as etl_router
from app.routes.kpis import router as kpis_router

app.include_router(auth_router.router)
app.include_router(catalog_router.router)
app.include_router(etl_router.router)
app.include_router(kpis_router, tags=["KPIs"])


@app.get("/health")
def health():
    return {"status": "ok"}
