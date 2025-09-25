# app/routes/etl.py
import os, re, io, base64, math
from typing import Any, Dict, Optional, List
import pandas as pd
import jaydebeapi
import httpx
from fastapi import APIRouter, Depends, HTTPException, Header

import jwt  # PyJWT

router = APIRouter(prefix="/etl", tags=["etl"])  # <--- IMPORTANTE

# === Config ===
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_ALG = os.getenv("JWT_ALG", "HS256")
JWT_AUD = os.getenv("JWT_AUD")
JWT_ISS = os.getenv("JWT_ISS")

N8N_BASE_URL = os.getenv("N8N_BASE_URL", "http://localhost:5678")
N8N_API_KEY = os.getenv("N8N_API_KEY")
# Webhook de ingesta (usa /webhook-test en pruebas)
N8N_INGEST_ENDPOINT = os.getenv("N8N_INGEST_ENDPOINT", "/webhook-test/ingest_ibmi")

DEFAULT_LIMIT = int(os.getenv("ETL_DEFAULT_LIMIT", "1000"))
MAX_LIMIT = int(os.getenv("ETL_MAX_LIMIT", "200000"))
DEFAULT_BATCH = int(os.getenv("ETL_BATCH_SIZE", "500"))
REQUEST_TIMEOUT = float(os.getenv("ETL_TIMEOUT_SEC", "60"))


# === Auth helpers ===
def require_jwt(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    token = authorization.split(" ", 1)[1].strip()
    options = {"verify_aud": bool(JWT_AUD)}
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


# === IBM i helpers ===
def _safe_ident(name: str) -> str:
    if not isinstance(name, str):
        raise HTTPException(status_code=400, detail="Identifier must be text")
    name = name.strip().upper()
    if not re.fullmatch(r"[A-Z0-9_#$@][A-Z0-9_#$@]*", name):
        raise HTTPException(status_code=400, detail=f"Invalid identifier: {name}")
    return name


def _conn_from_claims(claims: Dict[str, Any]):
    host = claims.get("host")
    user = claims.get("sub") or claims.get("user")
    pwd_b64 = claims.get("pwd_b64")
    if not host or not user or not pwd_b64:
        raise HTTPException(
            status_code=401,
            detail="Missing IBM i credentials in token (pwd_b64). Re-login with AUTH_EMBED_PWD=true.",
        )
    try:
        password = base64.b64decode(pwd_b64).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=401, detail="Corrupted credentials in token")

    jar = os.getenv("JT400_JAR", os.path.abspath("drivers/jt400.jar"))
    if not os.path.exists(jar):
        raise HTTPException(status_code=500, detail=f"JT400_JAR not found: {jar}")

    jclassname = "com.ibm.as400.access.AS400JDBCDriver"
    url = f"jdbc:as400://{host};prompt=false;naming=system"
    return jaydebeapi.connect(jclassname, url, [user, password], jar)


def _df_records(df: pd.DataFrame) -> List[Dict[str, Optional[str]]]:
    # Convierte todo a string; NaN -> None (para jsonb_to_recordset en Postgres)
    out: List[Dict[str, Optional[str]]] = []
    for rec in df.to_dict(orient="records"):
        norm = {}
        for k, v in rec.items():
            if pd.isna(v):
                norm[k] = None
            else:
                norm[k] = str(v)
        out.append(norm)
    return out


# === Endpoint: enviar a n8n ===
@router.post("/ingest")
async def etl_ingest(payload: Dict[str, Any], user=Depends(require_jwt)):
    """
    Body esperado (desde tu frontend):
      {
        "schema": schema,   # o "library"
        "table": table,
        "limit": 200,            # opcional (default 1000)
        "batchSize": 500         # opcional (default 500)
      }
    """
    schema = _safe_ident(payload.get("schema") or payload.get("library") or "")
    table = _safe_ident(payload.get("table") or "")
    limit = int(payload.get("limit") or DEFAULT_LIMIT)
    if limit < 1 or limit > MAX_LIMIT:
        raise HTTPException(
            status_code=400, detail=f"limit must be between 1 and {MAX_LIMIT}"
        )
    batch_size = int(payload.get("batchSize") or DEFAULT_BATCH)
    if batch_size < 1 or batch_size > 5000:
        raise HTTPException(
            status_code=400, detail="batchSize must be between 1 and 5000"
        )

    ident = f'"{schema}"."{table}"'
    sql = f"SELECT * FROM {ident} FETCH FIRST {limit} ROWS ONLY"

    # 1) Leer datos desde IBM i
    conn = _conn_from_claims(user)
    try:
        df = pd.read_sql(sql, conn)  # warning de pandas es esperado con jaydebeapi
    finally:
        try:
            conn.close()
        except:
            pass

    items = _df_records(df)
    total = len(items)
    if total == 0:
        return {"schema": schema, "table": table, "rows": 0, "batches": 0, "n8n": []}

    # 2) Enviar a n8n en lotes
    headers = {"Content-Type": "application/json"}
    if N8N_API_KEY:
        headers["X-N8N-API-KEY"] = N8N_API_KEY
    url = f"{N8N_BASE_URL}{N8N_INGEST_ENDPOINT}"

    batches = math.ceil(total / batch_size)
    results = []
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for i in range(batches):
            chunk = items[i * batch_size : (i + 1) * batch_size]
            body = {
                "schema": schema.lower(),  # añade schema (mejor en minúsculas para Postgres)
                "table": table.lower(),  # añade table
                "items": chunk,
                "batchSize": batch_size,
            }
            resp = await client.post(url, json=body, headers=headers)
            if resp.status_code >= 400:
                # Detener y reportar el error de n8n
                raise HTTPException(
                    status_code=502,
                    detail=f"n8n ingest failed (batch {i+1}/{batches}): {resp.text}",
                )
            results.append({"batch": i + 1, "status": resp.status_code})

    return {
        "schema": schema,
        "table": table,
        "rows": total,
        "batches": batches,
        "n8n": results,
    }
