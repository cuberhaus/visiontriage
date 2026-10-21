"""FastAPI surface for VisionTriage.

Weekend 1: health check plus a synchronous /triage endpoint that runs the
graph in-process. Weekend 4 puts the demo UI in front of this.

Run:  uvicorn visiontriage.api:app --reload --port 8080
"""

from fastapi import FastAPI
from pydantic import BaseModel

from visiontriage.graph import triage
from visiontriage.schemas import TriageReport

app = FastAPI(title="VisionTriage", version="0.1.0")


class TriageRequest(BaseModel):
    image_id: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/triage", response_model=TriageReport)
def run_triage(request: TriageRequest) -> TriageReport:
    return triage(request.image_id)
