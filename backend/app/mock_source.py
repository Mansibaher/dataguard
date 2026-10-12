from fastapi import FastAPI, Query
from .seed import sales_rows

app = FastAPI(title="Synthetic offline HTTP source")


@app.get("/sales")
def sales(page: int = Query(1, ge=1), size: int = Query(100, ge=1, le=1000)):
    rows = sales_rows(240, True)
    start = (page - 1) * size
    return {
        "rows": rows[start : start + size],
        "has_more": start + size < len(rows),
        "synthetic": True,
    }
