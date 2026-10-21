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

1. **Weekend 1 (this skeleton):** end-to-end loop, tracing on. Repo, Docker
   Compose, Anomalib tool behind an MCP server, 3-node LangGraph graph
   (investigate → diagnose → report), LangSmith tracing, one happy path.
   *Exit criterion: one image runs end to end and its trace is visible.*
2. **Weekend 2:** retrieval + human. RAG over the synthetic maintenance
   manuals with citations in the report, human-approval interrupt before
   filing, retry/error paths, versioned prompt files, real Anomalib
   (FastFlow/PatchCore) behind the MCP server instead of the stub.
   *Exit criterion: the agent cites a manual section and waits for approval.*
3. **Weekend 3:** evals. Golden dataset (~40 cases: anomalous, normal, and
   adversarial prompt-injection manuals), LangSmith evaluators for verdict
   accuracy, tool-selection correctness and citation faithfulness, first
   full regression run, fix the two worst failure modes it exposes.
   *Exit criterion: a before/after results table (see below).*
4. **Weekend 4:** showcase. Minimal demo UI embedded as an interactive demo
   on [polcasacubertagil.com](https://polcasacubertagil.com), README
   architecture diagram and trace screenshots, 2-minute demo video, short
   write-up post.
   *Exit criterion: a hiring manager understands it in 90 seconds without
   cloning anything.*

Deliberately out of scope (scope discipline is part of the point): voice,
auth/multi-tenancy, Kubernetes, fine-tuning. Optional extension if time
allows: a reviewer agent that critiques the diagnosis before the human
sees it.

## Eval results

*(Weekend 3: before/after table goes here, generated from LangSmith runs.)*
