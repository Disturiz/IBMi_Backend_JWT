import os, httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/n8n")
async def health_n8n():
    url = os.getenv("N8N_WEBHOOK_URL")
    if not url:
        raise HTTPException(400, "N8N_WEBHOOK_URL no configurado")
    base = url.split("/webhook")[0] if "/webhook" in url else url
    try:
        async with httpx.AsyncClient(timeout=5.0) as cx:
            r = await cx.get(base)
        return {"ok": r.status_code < 500, "status": r.status_code, "target": base}
    except httpx.HTTPError as e:
        raise HTTPException(503, f"n8n no accesible: {e.__class__.__name__}")
