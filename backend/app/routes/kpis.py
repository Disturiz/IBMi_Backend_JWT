# backend/app/routes/kpis.py
from __future__ import annotations

import os
from pathlib import Path
from datetime import date
from typing import Optional, Literal

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

# === Cargar .env (backend/.env) ===
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ENV_PATH, override=True)

router = APIRouter()

# === Engine perezoso (PG_DSN o variables separadas) ===
_ENGINE = None  # cache global


def _build_engine_now():
    dsn = (os.getenv("PG_DSN") or "").strip()
    if dsn:
        eng = create_engine(dsn, pool_pre_ping=True, future=True)
        print(f"[DB] Using PG_DSN | driver={eng.dialect.driver}")
        return eng

    host = os.getenv("PG_HOST")
    user = os.getenv("PG_USER")
    password = os.getenv("PG_PASSWORD")
    port = int(os.getenv("PG_PORT", "6543"))
    db = os.getenv("PG_DB", "postgres")
    sslmode = os.getenv("PG_SSLMODE", "require")

    missing = []
    if not host:
        missing.append("PG_HOST")
    if not user:
        missing.append("PG_USER")
    if not password:
        missing.append("PG_PASSWORD")
    if missing:
        raise RuntimeError(
            "Config DB incompleta. Faltan: "
            + ", ".join(missing)
            + ". Define PG_DSN o bien PG_HOST/PG_USER/PG_PASSWORD."
        )

    url = URL.create(
        "postgresql+psycopg",  # psycopg v3
        username=user,
        password=password,  # texto plano
        host=host,
        port=port,
        database=db,
        query={"sslmode": sslmode},
    )
    eng = create_engine(url, pool_pre_ping=True, future=True)
    print(f"[DB] Using parts | driver={eng.dialect.driver}")
    return eng


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = _build_engine_now()
    return _ENGINE


# === Config tabla/vista de KPIs ===
PG_SCHEMA = os.getenv("PG_SCHEMA", "analytics")
PG_TABLE = os.getenv("PG_TABLE", "ventaspf_utf8")


# === Modelos / utilidades ===
class KpiQuery(BaseModel):
    date_from: date
    date_to: date
    series_granularity: Literal["daily", "weekly", "monthly"] = "monthly"
    country: Optional[str] = None
    city: Optional[str] = None
    limit_top: int = 10
    top_dim: Literal["product", "city", "country"] = "product"
    metric: Literal["totalrev", "qty"] = "totalrev"


def _granularity_token(g: str) -> str:
    return {"daily": "day", "weekly": "week", "monthly": "month"}[g]


def _label_column(dim: str) -> str:
    return {"product": "product", "city": "city", "country": "country"}[dim]


# === Endpoint de diagnóstico rápido ===
@router.get("/__dbg/check")
def dbg_check():
    try:
        eng = _get_engine()
        with eng.begin() as conn:
            who = conn.execute(
                text("select current_user, current_database()")
            ).fetchone()
            tbl = f"{PG_SCHEMA}.{PG_TABLE}"
            exists = conn.execute(text("select to_regclass(:t)"), {"t": tbl}).scalar()
        return {
            "ok": True,
            "user": who[0],
            "db": who[1],
            "table": tbl,
            "table_exists": bool(exists),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# === Endpoint principal KPIs ===
@router.post("/kpis/query")
def kpis_query(q: KpiQuery):
    gran = _granularity_token(q.series_granularity)
    label_col = _label_column(q.top_dim)
    metric_col = "totalrev" if q.metric == "totalrev" else "qty"
    qualified = f'"{PG_SCHEMA}"."{PG_TABLE}"'

    # CTE filtrado con CAST explícito para evitar ambigüedad de tipos
    base_cte = f"""
    WITH filtered AS (
        SELECT
            orderdate::date AS d,
            qty, totalrev, product, city, country
        FROM {qualified}
        WHERE (orderdate::text ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$' OR orderdate::text IS NOT NULL)
          AND orderdate::date BETWEEN :date_from AND :date_to
          AND (COALESCE(CAST(:country AS text), '') = '' OR country = CAST(:country AS text))
          AND (COALESCE(CAST(:city    AS text), '') = '' OR city    = CAST(:city    AS text))
    )
    """

    timeseries_sql = text(
        base_cte
        + """
        SELECT
            date_trunc(CAST(:granularity AS text), d) AS dt,
            SUM(totalrev) AS totalrev,
            SUM(qty)      AS qty
        FROM filtered
        GROUP BY 1
        ORDER BY 1
        """
    )

    top_sql = text(
        base_cte
        + f"""
        SELECT
            {label_col} AS label,
            SUM(totalrev) AS totalrev,
            SUM(qty)      AS qty
        FROM filtered
        GROUP BY {label_col}
        ORDER BY SUM({metric_col}) DESC
        LIMIT :limit_top
        """
    )

    params = {
        "date_from": q.date_from,
        "date_to": q.date_to,
        "granularity": gran,  # 'day' | 'week' | 'month'
        "country": q.country,
        "city": q.city,
        "limit_top": q.limit_top,
    }

    try:
        with _get_engine().begin() as conn:
            ts_rows = [dict(r._mapping) for r in conn.execute(timeseries_sql, params)]
            top_rows = [dict(r._mapping) for r in conn.execute(top_sql, params)]

        return {
            "meta": {
                "date_from": str(q.date_from),
                "date_to": str(q.date_to),
                "series_granularity": q.series_granularity,
                "applied_filters": {"country": q.country, "city": q.city},
                "metric": q.metric,
                "top_dim": q.top_dim,
                "limit_top": q.limit_top,
            },
            "timeseries": [
                {
                    "dt": r["dt"].date().isoformat(),
                    "totalrev": float(r["totalrev"] or 0),
                    "qty": float(r["qty"] or 0),
                }
                for r in ts_rows
            ],
            "top": [
                {
                    "label": (r["label"] or "N/A"),
                    "totalrev": float(r["totalrev"] or 0),
                    "qty": float(r["qty"] or 0),
                }
                for r in top_rows
            ],
            "top_dim": q.top_dim,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")
