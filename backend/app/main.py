# backend/app/main.py
import os, io, re, time, datetime as dt
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
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
from .routes import auth as auth_router
from .routes import kpis as kpis_router
from .routes import catalog as catalog_router
from .routes import etl as etl_router

app.include_router(auth_router.router)
app.include_router(kpis_router.router)
app.include_router(catalog_router.router)
app.include_router(etl_router.router)


@app.get("/health")
def health():
    return {"status": "ok"}
