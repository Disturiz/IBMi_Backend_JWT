# app/auth.py
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from jose import jwt, JWTError  # (ExpiredSignatureError hereda de JWTError)

router = APIRouter()
bearer = HTTPBearer()  # lee Authorization: Bearer <token>

# --- Config (env) ---
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")  # ¡pon uno fuerte en .env!
JWT_ALG = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXP_MIN = int(os.getenv("JWT_EXP_MINUTES", "60"))
JWT_ISS = os.getenv("JWT_ISSUER", "ibmi-backend")


# --- Modelos ---
class LoginIn(BaseModel):
    host: str
    user: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Helpers JWT ---
def create_access_token(sub: str, extra: Dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": sub,  # sujeto (usuario)
        "iss": JWT_ISS,  # emisor
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=JWT_EXP_MIN)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


async def require_jwt(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
) -> Dict[str, Any]:
    """Dependencia: valida el JWT y devuelve el payload decodificado."""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")


# Alias para compatibilidad (las rutas que importen require_auth seguirán funcionando)
require_auth = require_jwt


# --- Endpoints ---
@router.post("/login", response_model=TokenOut)
def login(body: LoginIn) -> TokenOut:
    # Nota: aquí solo emites el token. Si quieres validar credenciales contra IBM i,
    # hazlo antes de generar el token (y lanza 401 en caso de error).
    token = create_access_token(body.user, extra={"host": body.host})
    return TokenOut(access_token=token)


@router.get("/me")
def whoami(payload: Dict[str, Any] = Depends(require_auth)):
    """Endpoint de prueba para validar rápidamente el JWT."""
    return {
        "sub": payload.get("sub"),
        "iss": payload.get("iss"),
        "host": payload.get("host"),
    }
