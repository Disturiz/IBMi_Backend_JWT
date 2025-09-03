# backend/app/services/ibmi.py
# -*- coding: utf-8 -*-

import os
import io
import csv
import pathlib
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv, find_dotenv, dotenv_values

# -----------------------------------------------------------------------------
# Carga del .env (determinista y a prueba de valores con espacios)
# -----------------------------------------------------------------------------
ENV_PATH = find_dotenv(usecwd=True)
if not ENV_PATH:
    raise RuntimeError(
        "No se encontró .env; inicia Uvicorn desde la raíz del proyecto "
        "(p. ej. `python -m uvicorn backend.app.main:app --reload`)"
    )

# 1) Carga estándar
load_dotenv(ENV_PATH, override=True)

# 2) Fusión de valores por si alguno no entró (p.ej. espacios en IBMI_JDBC_URL)
for k, v in dotenv_values(ENV_PATH).items():
    if os.getenv(k) in (None, ""):
        os.environ[k] = "" if v is None else str(v)


# -----------------------------------------------------------------------------
# Validaciones de configuración
# -----------------------------------------------------------------------------
def _must_env(name: str) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        raise RuntimeError(f"Falta variable de entorno: {name}")
    return v


JT400_JAR = os.path.abspath(_must_env("JT400_JAR"))
if not pathlib.Path(JT400_JAR).is_file():
    raise FileNotFoundError(f"jt400.jar no existe en: {JT400_JAR}")

# -----------------------------------------------------------------------------
# Conexión JDBC con JayDeBeApi
# -----------------------------------------------------------------------------
import jaydebeapi  # requiere JPype instalado


def get_ibmi_connection():
    """
    Abre conexión JDBC a IBM i usando JayDeBeApi + JT400.
    Requiere en .env:
      - JT400_JAR -> ruta absoluta al jt400.jar
      - IBMI_JDBC_URL -> jdbc:as400://HOST;opciones...
      - IBMI_USER / IBMI_PASSWORD
    """
    jdbc_url = _must_env(
        "IBMI_JDBC_URL"
    )  # ¡en .env ponlo entre comillas si hay espacios!
    user = _must_env("IBMI_USER")
    password = _must_env("IBMI_PASSWORD")

    return jaydebeapi.connect(
        "com.ibm.as400.access.AS400JDBCDriver",
        jdbc_url,
        {"user": user, "password": password},
        jars=[JT400_JAR],  # ¡lista, no string!
    )


# -----------------------------------------------------------------------------
# Catálogo (schemas y tablas)
# -----------------------------------------------------------------------------
def list_schemas(pattern: str = "%") -> List[str]:
    sql = """
        SELECT DISTINCT TABLE_SCHEMA
        FROM QSYS2.SYSTABLES
        WHERE UPPER(TABLE_SCHEMA) LIKE ?
        ORDER BY TABLE_SCHEMA
        FETCH FIRST 200 ROWS ONLY
    """
    like = (pattern or "%").replace("*", "%").upper()
    with get_ibmi_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (like,))
        rows = cur.fetchall()
    return [r[0] for r in rows]


def list_tables(library: str, pattern: str = "%", limit: int = 20) -> List[str]:
    sql = """
        SELECT TABLE_NAME
        FROM QSYS2.SYSTABLES
        WHERE TABLE_SCHEMA = ?
          AND UPPER(TABLE_NAME) LIKE ?
        ORDER BY TABLE_NAME
        FETCH FIRST ? ROWS ONLY
    """
    lib = (library or "").upper()
    like = (pattern or "%").replace("*", "%").upper()
    lim = max(1, int(limit or 20))
    with get_ibmi_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, (lib, like, lim))
        rows = cur.fetchall()
    return [r[0] for r in rows]


# -----------------------------------------------------------------------------
# Extracción de datos
# -----------------------------------------------------------------------------
def _fetch_rows(library: str, table: str, limit: int) -> List[Dict[str, Any]]:
    lib = library.upper()
    tbl = table.upper()
    lim = max(1, int(limit or 1))
    sql = f'SELECT * FROM "{lib}"."{tbl}" FETCH FIRST {lim} ROWS ONLY'
    with get_ibmi_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def extract_to_json(library: str, table: str, limit: int = 200) -> Dict[str, Any]:
    """
    Formato que espera el frontend para el preview.
    Devuelve: {"count": N, "rows": [ {...}, ... ]}
    """
    rows = _fetch_rows(library, table, limit)
    return {"count": len(rows), "rows": rows}


def extract_to_csv(library: str, table: str, limit: int = 200) -> Tuple[bytes, str]:
    """
    Devuelve (contenido_csv_en_bytes, nombre_de_archivo.csv)
    """
    rows = _fetch_rows(library, table, limit)
    if not rows:
        return b"NO_DATA\n", f"{library}_{table}.csv"
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8"), f"{library}_{table}.csv"


def extract_to_xlsx(library: str, table: str, limit: int = 200) -> Tuple[bytes, str]:
    """
    Intenta XLSX con pandas. Si falta xlsxwriter, prueba openpyxl.
    Si faltan ambos o no hay pandas, hace fallback a CSV.
    """
    # 1) Si no hay filas, devolvemos CSV mínimo para no entregar XLSX vacío
    rows = _fetch_rows(library, table, limit)
    if not rows:
        return extract_to_csv(library, table, limit)

    # 2) Intentar con pandas
    try:
        import pandas as pd
    except ImportError:
        # Sin pandas -> CSV
        return extract_to_csv(library, table, limit)

    # 3) Elegir motor disponible: xlsxwriter -> openpyxl -> CSV
    engine = None
    try:
        import xlsxwriter  # noqa: F401

        engine = "xlsxwriter"
    except ImportError:
        try:
            import openpyxl  # noqa: F401

            engine = "openpyxl"
        except ImportError:
            # Sin motores XLSX -> CSV
            return extract_to_csv(library, table, limit)

    # 4) Generar XLSX en memoria
    import io as _io

    buf = _io.BytesIO()
    df = pd.DataFrame(rows)
    with pd.ExcelWriter(buf, engine=engine) as xw:
        df.to_excel(xw, index=False, sheet_name=(table or "Sheet1")[:31])

    return buf.getvalue(), f"{library}_{table}.xlsx"


# -----------------------------------------------------------------------------
# Utilidades de diagnóstico (opcionales)
# -----------------------------------------------------------------------------
def debug_info() -> Dict[str, Any]:
    """Útil para exponer en /debug/env."""
    jar = os.getenv("JT400_JAR", "")
    return {
        "cwd": os.getcwd(),
        "dotenv": ENV_PATH,
        "JT400_JAR": jar,
        "jt400_exists": pathlib.Path(jar).is_file(),
        "IBMI_JDBC_URL": os.getenv("IBMI_JDBC_URL"),
        "IBMI_USER": os.getenv("IBMI_USER"),
        # NEVER devolver IBMI_PASSWORD en respuestas reales
    }


__all__ = [
    "get_ibmi_connection",
    "list_schemas",
    "list_tables",
    "extract_to_json",
    "extract_to_csv",
    "extract_to_xlsx",
    "debug_info",
]
