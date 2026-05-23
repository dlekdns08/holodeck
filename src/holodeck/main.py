from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .config import CACHE_DIR

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "static"

app = FastAPI(title="Holodeck", version="0.1.0")
app.include_router(api_router, prefix="/api")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
# Serves last-frame JPEGs (and any other provider-cached artifacts) generated at
# runtime. Kept separate from /static so it's clear what's committed vs. cache.
app.mount("/cache", StaticFiles(directory=CACHE_DIR), name="cache")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
