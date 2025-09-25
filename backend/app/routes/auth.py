# app/routes/auth.py
import os, time, base64
from typing import Any, Dict
import jwt  # PyJWT
import jaydebeapi
from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["auth"])

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_ALG = os.getenv("JWT_ALG", "HS256")
JWT_EXP_SECONDS = int(os.getenv("JWT_EXP_SECONDS", "3600"))
AUTH_DEVMODE = os.getenv("AUTH_DEVMODE", "false").lower() in {"1", "true", "yes"}
AUTH_EMBED_PWD = os.getenv("AUTH_EMBED_PWD", "true").lower() in {"1", "true", "yes"}


def _extract(
    payload: Dict[str, Any], *keys: str, req: bool = True, name: str = "field"
):
    for k in keys:
        v = payload.get(k)
        if isinstance(v, str):
            v = v.strip()
        if v:
            return v
    if req:
        raise HTTPException(
            status_code=400, detail=f"Missing {name}: one of {', '.join(keys)}"
        )
    return None


def _validate_ibmi_login(host: str, user: str, password: str) -> None:
    if AUTH_DEVMODE:
        return
    jar = os.getenv("JT400_JAR", os.path.abspath("drivers/jt400.jar"))
    if not os.path.exists(jar):
        raise HTTPException(status_code=500, detail=f"JT400_JAR not found: {jar}")
    jclassname = "com.ibm.as400.access.AS400JDBCDriver"
    url = f"jdbc:as400://{host};prompt=false"
    try:
        conn = jaydebeapi.connect(jclassname, url, [user, password], jar)
        cur = conn.cursor()
        cur.execute("SELECT CURRENT_DATE FROM SYSIBM.SYSDUMMY1")
        cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"IBM i login failed: {e}")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


def _issue_jwt(sub: str, host: str, password: str) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "host": host,
        "roles": ["user"],
        "iat": now,
        "exp": now + JWT_EXP_SECONDS,
    }
    if AUTH_EMBED_PWD:
        payload["pwd_b64"] = base64.b64encode(password.encode("utf-8")).decode("ascii")
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


@router.post("/login")
def login(payload: Dict[str, Any]):
    host = _extract(payload, "host", "hostname", "ibmi_host", name="host")
    user = _extract(payload, "user", "username", "ibmi_user", name="user")
    password = _extract(payload, "pass", "password", "ibmi_password", name="password")

    _validate_ibmi_login(host, user, password)
    token = _issue_jwt(sub=user, host=host, password=password)

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user,
        "host": host,
        "devmode": AUTH_DEVMODE,
        "pwd_embedded": AUTH_EMBED_PWD,
    }
