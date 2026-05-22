from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "static"

app = FastAPI(title="Holodeck", version="0.1.0")
app.include_router(api_router, prefix="/api")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
