# app/routes/kpis.py
import os
import httpx
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
import jwt  # PyJWT

router = APIRouter(prefix="/kpis", tags=["kpis"])

# --- Config vía entorno ---
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "http://localhost:5678")
# Usa /webhook para producción; /webhook-test para pruebas
N8N_ENDPOINT = os.getenv("N8N_ENDPOINT", "/webhook/etl-ibmi-kpis")
N8N_API_KEY = os.getenv("N8N_API_KEY")  # opcional
REQUEST_TIMEOUT = float(os.getenv("N8N_TIMEOUT_SEC", "60"))

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")  # cámbialo en prod
JWT_ALG = os.getenv("JWT_ALG", "HS256")
JWT_AUD = os.getenv("JWT_AUD")  # opcional (audience)
JWT_ISS = os.getenv("JWT_ISS")  # opcional (issuer)


class Filters(BaseModel):
    country: Optional[str] = None
    city: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    series_granularity: Optional[str] = None  # daily|weekly|monthly|quarterly|yearly
    limit_top: Optional[int] = 10
    # Cualquier otro filtro que uses en n8n:
    # zone: Optional[str] = None
    # product_code: Optional[str] = None
    # ...


def require_jwt(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """
    Valida un JWT en el header Authorization: Bearer <token>
    Devuelve el payload decodificado si es válido.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )

    token = authorization.split(" ", 1)[1].strip()
    options = {"verify_aud": bool(JWT_AUD)}  # solo verifica aud si está configurado
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALG],
            audience=JWT_AUD if JWT_AUD else None,
            issuer=JWT_ISS if JWT_ISS else None,
            options=options,
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


@router.post("/query")
async def kpis_query(filters: Filters, user=Depends(require_jwt)):
    """
    Proxy autenticado: Frontend -> Backend (JWT) -> n8n
    Reenvía el JSON de filtros al webhook de n8n y devuelve el JSON resultante.
    """
    url = f"{N8N_BASE_URL}{N8N_ENDPOINT}"
    headers = {"Content-Type": "application/json"}

    if N8N_API_KEY:
        # Si protegiste el webhook con API Key personalizada en n8n
        headers["X-N8N-API-KEY"] = N8N_API_KEY

    # Puedes adjuntar metadata de usuario si te sirve en n8n:
    payload = filters.model_dump()
    payload["_auth"] = {
        "sub": user.get("sub"),
        "roles": user.get("roles"),
        "iss": user.get("iss"),
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code >= 400:
            # Regresa el texto de error de n8n para depurar
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        return resp.json()
    except httpx.RequestError as e:
        # Errores de red, timeouts, DNS, etc.
        raise HTTPException(status_code=502, detail=f"Upstream error (n8n): {e}")
