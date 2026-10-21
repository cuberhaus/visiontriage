# VisionTriage

**Agentic incident analyst for industrial cameras.** A LangGraph state machine
takes anomaly detections from real computer-vision models, investigates them
with tools exposed over MCP, consults maintenance documentation via RAG, and
drafts a triage report a human approves or rejects. Every run is traced and
evaluated in LangSmith.

Built as public evidence for agentic-AI engineering on top of a production
computer-vision stack. Data is public/synthetic only (MVTec AD plus
self-written maintenance manuals); no employer material anywhere in this repo.

## Architecture

```text
image → CV tools (Anomalib) ── MCP (Streamable HTTP) ──► LangGraph graph
                                                          investigate →
                                                          retrieve (RAG) →
                                                          diagnose →
                                                          draft report →
                                                          [HUMAN APPROVAL]
                                                                │
                              LangSmith traces + evals ◄────────┘
                                                                │
                              FastAPI API + demo UI ◄───────────┘
```

## Status: Weekend 1 skeleton

What runs today:

- `visiontriage/mcp_server.py` — FastMCP server with `analyze_image` and
  `image_metadata` tools. The detector is a deterministic stub so the loop
  runs anywhere; Anomalib (FastFlow/PatchCore) lands behind the `cv` extra.
- `visiontriage/graph.py` — 3-node LangGraph graph (investigate → diagnose →
  report) with a confidence floor. It reaches the tools through a thin
  transport shim; Weekend 2 swaps the shim for a real MCP client without
  touching node code.
- `visiontriage/api.py` — FastAPI `GET /health`, `POST /triage`.
- Tests + CI, Docker Compose for MCP server and API.

## Run it

```bash
uv sync --extra dev
uv run python -m visiontriage.graph     # demo: one defect, one clean image
uv run pytest -q
docker compose up --build               # MCP on :8000, API on :8080
```

Copy `.env.example` to `.env` and add a LangSmith key to see traces.

## Roadmap

1. **Weekend 1 (this skeleton):** end-to-end loop, tracing on.
2. **Weekend 2:** RAG over manuals with citations, human-approval interrupt,
   retries, versioned prompts, real Anomalib behind the MCP server.
3. **Weekend 3:** golden dataset (~40 cases incl. adversarial), LangSmith
   evaluators (verdict accuracy, tool selection, citation faithfulness),
   first regression run and fixes.
4. **Weekend 4:** demo UI, results table, demo video, write-up.

Deliberately out of scope: voice, auth/multi-tenancy, Kubernetes,
fine-tuning. Optional extension: a reviewer agent that critiques the
diagnosis before the human sees it.

## Eval results

*(Weekend 3: before/after table goes here, generated from LangSmith runs.)*
