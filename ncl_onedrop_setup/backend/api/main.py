
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="NCL NuraulCortexLink API", version="0.1.0")

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'backend' / 'data'
DOCS = ROOT / 'docs' / 'product'

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/progress")
def progress():
    p = {
        "system": "NCL NuraulCortexLink",
        "insights_completed": 150,
        "insights_total": 500,
        "percent": round(150/500*100,2),
        "updated": ""}
    return JSONResponse(p)

@app.get("/roadmap")
def roadmap():
    fp = DOCS / 'roadmap_100_steps.md'
    txt = fp.read_text() if fp.exists() else ""
    return JSONResponse({"markdown": txt})

