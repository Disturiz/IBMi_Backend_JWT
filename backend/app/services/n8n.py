import os, httpx
from fastapi import HTTPException


async def enviar_a_n8n(payload: dict) -> dict:
    url = os.getenv("N8N_WEBHOOK_URL")
    if not url:
        raise HTTPException(400, "N8N_WEBHOOK_URL no configurado")
    try:
        timeout = httpx.Timeout(5.0, read=30.0)
        async with httpx.AsyncClient(timeout=timeout) as cx:
            r = await cx.post(url, json=payload)
    except httpx.RequestError as e:
        raise HTTPException(503, f"Conexión a n8n falló: {e.__class__.__name__}")
    if r.status_code not in (200, 201, 202):
        raise HTTPException(
            r.status_code, f"n8n respondió {r.status_code}: {r.text[:200]}"
        )
    return {"ok": True, "status": r.status_code}
