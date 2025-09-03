# app/routes/etl.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from ..auth import require_auth, require_jwt
from ..services.ibmi import get_ibmi_connection
import os, httpx

router = APIRouter()


class IngestIn(BaseModel):
    schema_: str = Field(
        "raw", alias="schema"
    )  # <— usa schema_ internamente, alias “schema” afuera
    table: str = Field("ventaspf")
    mode: str = Field("append")
    source: str = Field("ibmi")
    rows: List[Dict[str, Any]]

    class Config:
        allow_population_by_field_name = (
            True  # por si algún cliente te envía "schema_" en vez de "schema"
        )


@router.post("/ingest")
async def etl_ingest(body: dict, user=Depends(require_jwt)):
    url = (os.getenv("N8N_WEBHOOK_URL") or "").strip()
    if not url:
        raise HTTPException(500, "N8N_WEBHOOK_URL no configurado")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(url, json=body)
        return {
            "status": r.status_code,
            "ok": r.status_code < 300,
            "text": r.text[:1000],
        }
    except httpx.RequestError as e:
        raise HTTPException(502, f"Conexión a n8n falló: {e}")
