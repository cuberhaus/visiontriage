"""MCP server exposing the computer-vision tools.

This is the boundary that matters for the project: the LangGraph agent may
only reach the CV models through this server, over the MCP protocol. No
direct model imports on the agent side.

Weekend 1 state: the Anomalib-backed tool returns deterministic stub scores
so the full loop runs on a laptop without the CV stack installed. Weekend 1
exit criterion is the loop, not the model. Swap `_stub_analyze` for a real
Anomalib (FastFlow/PatchCore) predictor behind the `cv` extra:

    uv sync --extra cv

Run (Streamable HTTP, the current MCP transport; SSE is deprecated):

    python -m visiontriage.mcp_server
"""

import hashlib

from fastmcp import FastMCP

from visiontriage.schemas import Detection

mcp = FastMCP("visiontriage-cv")


def _stub_analyze(image_id: str) -> list[Detection]:
    """Deterministic placeholder for Anomalib inference.

    Hashes the image id so demos and tests are reproducible: ids starting
    with 'defect' read as anomalous, everything else as clean. Replace with
    a real model call; keep the Detection contract unchanged.
    """
    digest = hashlib.sha256(image_id.encode()).hexdigest()
    if image_id.startswith("defect"):
        return [
            Detection(
                label="scratch",
                score=0.75 + (int(digest[:2], 16) % 20) / 100.0,
                bbox=(12, 30, 64, 18),
            )
        ]
    return [Detection(label="none", score=0.05, bbox=None)]


@mcp.tool
def analyze_image(image_id: str) -> list[Detection]:
    """Run anomaly detection on one industrial-camera image.

    Returns a list of detections with per-defect confidence scores.
    A single 'none' detection with a low score means the image reads clean.
    """
    return _stub_analyze(image_id)


@mcp.tool
def image_metadata(image_id: str) -> dict:
    """Return basic metadata for an image (stub until real storage lands)."""
    return {"image_id": image_id, "source": "mvtec-ad", "width": 1024, "height": 1024}


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)
