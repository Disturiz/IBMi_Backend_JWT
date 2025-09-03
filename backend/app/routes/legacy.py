# app/routes/legacy.py
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
import io

from ..auth import require_auth
from ..services.ibmi import (
    list_schemas,
    list_tables,
    extract_to_json,
    extract_to_csv,
    extract_to_xlsx,
)

router = APIRouter()


class SchemasIn(BaseModel):
    pattern: str = Field("%", description="Patrón de búsqueda (ej. Q%)")


class TablesIn(BaseModel):
    library: str
    pattern: str = Field("%", description="Patrón de búsqueda (ej. CUST%)")
    limit: int = 20


class ExtractIn(BaseModel):
    library: str
    table: str
    limit: int = 1000


@router.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@router.post("/catalog/schemas")
def catalog_schemas(
    body: SchemasIn, user=Depends(require_auth)
) -> Dict[str, List[str]]:
    try:
        schemas = list_schemas(body.pattern)
        return {"schemas": schemas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/catalog")
def catalog_tables(
    body: TablesIn, user=Depends(require_auth)
) -> Dict[str, List[Dict[str, str]]]:
    try:
        items = [
            {"schema": body.library.upper(), "table": t}
            for t in list_tables(body.library, body.pattern, body.limit)
        ]
        return {"items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract")
def extract(body: ExtractIn, format: str = "json", user=Depends(require_auth)) -> Any:
    """
    Soporta:
      - /extract?format=json  -> {count, rows}
      - /extract?format=csv   -> descarga CSV
      - /extract?format=xlsx  -> descarga XLSX (si no hay pandas, hace fallback a CSV)
    """
    lib = body.library.upper()
    tbl = body.table.upper()
    lim = body.limit
    fmt = (format or "json").lower()

    try:
        if fmt == "json":
            return extract_to_json(lib, tbl, lim)

        elif fmt == "csv":
            content, fname = extract_to_csv(lib, tbl, lim)  # bytes, nombre.csv
            return StreamingResponse(
                io.BytesIO(content),
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="{fname}"'},
            )

        elif fmt in ("xlsx", "xls", "excel"):
            content, fname = extract_to_xlsx(
                lib, tbl, lim
            )  # bytes, nombre.xlsx o .csv si fallback
            media = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                if fname.lower().endswith(".xlsx")
                else "text/csv"
            )
            return StreamingResponse(
                io.BytesIO(content),
                media_type=media,
                headers={"Content-Disposition": f'attachment; filename="{fname}"'},
            )

        else:
            raise HTTPException(
                status_code=400, detail=f"Formato no soportado: {format}"
            )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
