
import os, io, re, time, datetime as dt
import pandas as pd
from fastapi import FastAPI, Body, Query, Response, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import jaydebeapi
import jwt  # PyJWT

JT400_JAR = os.getenv("JT400_JAR", os.path.abspath("drivers/jt400.jar"))
ALLOW_LIBS = [s.strip().upper() for s in os.getenv("ALLOW_LIBS", "").split(",") if s.strip()]
JWT_SECRET = os.getenv("JWT_SECRET", "dev-CHANGE-ME")
JWT_ALGO = os.getenv("JWT_ALGO", "HS256")
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "5"))

app = FastAPI(title="IBMi Extract API — JWT + Autocomplete")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

IDENT_RE = re.compile(r"^[A-Z0-9_#$@]+$")
def _validate_ident(s: str) -> str:
    s = (s or "").strip().upper()
    if not s or not IDENT_RE.match(s):
        raise HTTPException(status_code=400, detail=f"Identificador inválido: {s!r}")
    return s

def _humanize_db2_error(err: Exception) -> str:
    t = str(err)
    if "SQL0204" in t:
        return "SQL0204: Objeto no encontrado (verifique LIBRARY/TABLE y permisos)."
    if "SQL0443" in t or "not authorized" in t.lower() or "authorization" in t.lower():
        return "Permisos insuficientes para leer el objeto."
    if "Connection refused" in t or "Communications link failure" in t or "I/O error" in t:
        return "No se pudo conectar al host IBM i (host/puerto/VPN)."
    return t

def _connect(host: str, user: str, password: str):
    url = f"jdbc:as400://{host};prompt=false;naming=system;errors=full"
    driver = "com.ibm.as400.access.AS400JDBCDriver"
    try:
        return jaydebeapi.connect(driver, url, {"user": user, "password": password}, JT400_JAR)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error de conexión a IBM i: {e}")

def _make_token(host: str, user: str, password: str) -> str:
    now = int(time.time())
    exp = now + JWT_EXPIRE_MIN * 60
    payload = {"sub": user, "host": host, "user": user, "password": password, "iat": now, "exp": exp}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def _require_token(authorization: str = Header(...)):
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Formato de Authorization inválido")
    token = authorization.split(" ", 1)[1].strip()
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return data
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token inválido: {e}")

@app.post("/login")
async def login(payload: dict = Body(...)):
    host = (payload.get("host") or "").strip()
    user = (payload.get("user") or "").strip()
    password = (payload.get("password") or "").strip()
    if not (host and user and password):
        raise HTTPException(status_code=400, detail="Faltan credenciales o host.")

    conn = _connect(host, user, password)
    try:
        cur = conn.cursor()
        cur.execute("values(1)")
        _ = cur.fetchall()
    except Exception as e:
        raise HTTPException(status_code=401, detail="Credenciales inválidas: " + _humanize_db2_error(e))
    finally:
        try: cur.close(); conn.close()
        except Exception: pass

    token = _make_token(host, user, password)
    return {"access_token": token, "token_type": "bearer", "expires_in": JWT_EXPIRE_MIN * 60}

@app.post("/extract")
async def extract(payload: dict = Body(...), format: str = Query("json", pattern="^(json|csv|xlsx)$"), claims: dict = Depends(_require_token)):
    host = claims["host"]; user = claims["user"]; password = claims["password"]
    library = _validate_ident(payload.get("library"))
    table = _validate_ident(payload.get("table"))
    limit = max(1, min(int(payload.get("limit") or 200), 5000))

    conn = _connect(host, user, password)
    sql = f"SELECT * FROM {library}.{table} FETCH FIRST {limit} ROWS ONLY"
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        data = [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error ejecutando SQL: " + _humanize_db2_error(e))
    finally:
        try: cur.close(); conn.close()
        except Exception: pass

    if format == "csv":
        buf = io.StringIO()
        pd.DataFrame(data).to_csv(buf, index=False)
        return Response(content=buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{library}_{table}.csv"'})
    if format == "xlsx":
        import io as _io
        from openpyxl.utils import get_column_letter
        buf = _io.BytesIO()
        df = pd.DataFrame(data)
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            sheet = "datos"
            df.to_excel(writer, index=False, sheet_name=sheet)
            ws = writer.sheets[sheet]
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for i, col in enumerate(df.columns, start=1):
                col_vals = [str(col)] + df[col].astype(str).tolist()
                max_len = min(max((len(s) for s in col_vals), default=10), 60)
                ws.column_dimensions[get_column_letter(i)].width = max(10, max_len + 2)
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="{library}_{table}.xlsx"'})
    return {"rows": data, "count": len(data)}

@app.post("/catalog")
async def catalog(payload: dict = Body(...), claims: dict = Depends(_require_token)):
    host = claims["host"]; user = claims["user"]; password = claims["password"]
    library = (payload.get("library") or "").strip().upper()
    pattern = (payload.get("pattern") or "").strip().upper()
    limit = max(1, min(int(payload.get("limit") or 20), 50))

    conn = _connect(host, user, password)
    libs = ALLOW_LIBS[:] or ([library] if library else [])
    if not libs:
        raise HTTPException(status_code=400, detail="Debe especificar 'library' o configurar ALLOW_LIBS en el servidor.")

    where = "TABLE_SCHEMA IN (" + ",".join([f"'{_validate_ident(x)}'" for x in libs]) + ")"
    like_clause = ""
    params = []
    if pattern:
        like_clause = " AND TABLE_NAME LIKE ?"
        params.append(pattern.replace('*', '%').replace('?', '_'))

    sql = f"""
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM QSYS2.SYSTABLES
        WHERE {where} {like_clause}
        FETCH FIRST {limit} ROWS ONLY
    """
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [{"schema": r[0], "table": r[1]} for r in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error consultando catálogo: " + _humanize_db2_error(e))
    finally:
        try: cur.close(); conn.close()
        except Exception: pass

    return {"items": rows, "count": len(rows), "libs": libs}

@app.post("/catalog/schemas")
async def catalog_schemas(payload: dict = Body(...), claims: dict = Depends(_require_token)):
    host = claims["host"]; user = claims["user"]; password = claims["password"]
    pattern = (payload.get("pattern") or "").strip().upper()
    limit = max(1, min(int(payload.get("limit") or 20), 100))

    conn = _connect(host, user, password)
    where = "1=1"
    params = []
    if pattern:
        where += " AND TABLE_SCHEMA LIKE ?"
        params.append(pattern.replace('*', '%').replace('?', '_'))

    sql = f"""
        SELECT DISTINCT TABLE_SCHEMA
        FROM QSYS2.SYSTABLES
        WHERE {where}
        FETCH FIRST {limit} ROWS ONLY
    """
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [r[0] for r in cur.fetchall()]
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error listando schemas: " + _humanize_db2_error(e))
    finally:
        try: cur.close(); conn.close()
        except Exception: pass

    if ALLOW_LIBS:
        rows = [s for s in rows if s.upper() in ALLOW_LIBS]
    return {"schemas": rows, "count": len(rows)}

@app.get("/health")
def health():
    return {"ok": True}
