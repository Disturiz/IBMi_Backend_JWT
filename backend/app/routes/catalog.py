# app/routes/catalog.py
import os, re, io, base64
from typing import Any, Dict, List, Optional
import pandas as pd
import jaydebeapi
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import StreamingResponse
import jwt  # PyJWT

router = APIRouter(tags=["catalog"])

# === JWT config (igual que en kpis.py) ===
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret")
JWT_ALG = os.getenv("JWT_ALG", "HS256")
JWT_AUD = os.getenv("JWT_AUD")
JWT_ISS = os.getenv("JWT_ISS")


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


# === Helpers IBM i ===
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
            detail="Missing IBM i credentials in token. Set AUTH_EMBED_PWD=true and re-login.",
        )
    try:
        password = base64.b64decode(pwd_b64).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=401, detail="Corrupted credentials in token")

    jar = os.getenv("JT400_JAR", os.path.abspath("drivers/jt400.jar"))
    if not os.path.exists(jar):
        raise HTTPException(status_code=500, detail=f"JT400_JAR not found: {jar}")
    jclassname = "com.ibm.as400.access.AS400JDBCDriver"
    # naming=system para formar SCHEMA.TABLE
    url = f"jdbc:as400://{host};prompt=false;naming=system"
    return jaydebeapi.connect(jclassname, url, [user, password], jar)


# === Endpoints ===


@router.post("/catalog/schemas")
def list_schemas(user=Depends(require_jwt)):
    sql = "SELECT SCHEMA_NAME FROM QSYS2.SYSSCHEMAS ORDER BY SCHEMA_NAME FETCH FIRST 200 ROWS ONLY"
    conn = _conn_from_claims(user)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        schemas = [r[0] for r in rows]
        return {"schemas": schemas}
    finally:
        try:
            cur.close()
        except:
            pass
        try:
            conn.close()
        except:
            pass


@router.post("/catalog/tables")
def list_tables(payload: Dict[str, Any], user=Depends(require_jwt)):
    schema = _safe_ident(payload.get("schema") or payload.get("library") or "")
    sql = """
        SELECT TABLE_NAME
        FROM QSYS2.SYSTABLES
        WHERE TABLE_SCHEMA = ?
          AND TABLE_TYPE = 'T'
        ORDER BY TABLE_NAME
        FETCH FIRST 500 ROWS ONLY
    """
    conn = _conn_from_claims(user)
    try:
        cur = conn.cursor()
        cur.execute(sql, [schema])
        rows = cur.fetchall()
        tables = [r[0] for r in rows]
        return {"schema": schema, "tables": tables}
    finally:
        try:
            cur.close()
        except:
            pass
        try:
            conn.close()
        except:
            pass


@router.post("/catalog/columns")
def list_columns(payload: Dict[str, Any], user=Depends(require_jwt)):
    schema = _safe_ident(payload.get("schema") or payload.get("library") or "")
    table = _safe_ident(payload.get("table") or "")
    sql = """
        SELECT COLUMN_NAME, DATA_TYPE, LENGTH, NUMERIC_SCALE
        FROM QSYS2.SYSCOLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """
    conn = _conn_from_claims(user)
    try:
        cur = conn.cursor()
        cur.execute(sql, [schema, table])
        cols = [
            {"name": r[0], "type": r[1], "length": r[2], "scale": r[3]}
            for r in cur.fetchall()
        ]
        return {"schema": schema, "table": table, "columns": cols}
    finally:
        try:
            cur.close()
        except:
            pass
        try:
            conn.close()
        except:
            pass


@router.post("/preview")
def preview_table(payload: Dict[str, Any], user=Depends(require_jwt)):
    schema = _safe_ident(payload.get("schema") or payload.get("library") or "")
    table = _safe_ident(payload.get("table") or "")
    limit = int(payload.get("limit") or 100)
    if limit < 1 or limit > 10000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 10000")

    ident = f'"{schema}"."{table}"'
    sql = f"SELECT * FROM {ident} FETCH FIRST {limit} ROWS ONLY"

    conn = _conn_from_claims(user)
    try:
        df = pd.read_sql(sql, conn)
        return {
            "schema": schema,
            "table": table,
            "limit": limit,
            "rows": df.to_dict(orient="records"),
        }
    finally:
        try:
            conn.close()
        except:
            pass


@router.post("/extract")
def extract_table(payload: Dict[str, Any], user=Depends(require_jwt)):
    schema = _safe_ident(payload.get("schema") or payload.get("library") or "")
    table = _safe_ident(payload.get("table") or "")
    fmt = (payload.get("format") or "json").lower()
    limit = payload.get("limit")
    limit_clause = ""
    if limit:
        limit = int(limit)
        if limit < 1 or limit > 1000000:
            raise HTTPException(status_code=400, detail="limit out of range")
        limit_clause = f" FETCH FIRST {limit} ROWS ONLY"

    ident = f'"{schema}"."{table}"'
    sql = f"SELECT * FROM {ident}{limit_clause}"

    conn = _conn_from_claims(user)
    try:
        df = pd.read_sql(sql, conn)

        if fmt == "json":
            return {
                "schema": schema,
                "table": table,
                "count": len(df),
                "rows": df.to_dict(orient="records"),
            }
        elif fmt == "csv":
            buff = io.StringIO()
            df.to_csv(buff, index=False)
            buff.seek(0)
            filename = f"{schema}_{table}.csv"
            return StreamingResponse(
                buff,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        elif fmt == "xlsx":
            buff = io.BytesIO()
            with pd.ExcelWriter(buff, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="data")
            buff.seek(0)
            filename = f"{schema}_{table}.xlsx"
            return StreamingResponse(
                buff,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        else:
            raise HTTPException(status_code=400, detail="format must be json|csv|xlsx")
    finally:
        try:
            conn.close()
        except:
            pass
