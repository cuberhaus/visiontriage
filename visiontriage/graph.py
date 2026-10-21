"""LangGraph state machine for VisionTriage.

Weekend 1 graph (three nodes, linear):

    investigate -> diagnose -> report

Weekend 2 grows this into the full design: conditional routing after
investigation, a RAG retrieval node over the maintenance manuals, guardrail
checks (confidence floor, tool-call budget) and a human-approval interrupt
before the report is filed.

The graph calls the CV tools through MCP-shaped plain functions for now
(`visiontriage.mcp_server._stub_analyze` via a thin client shim) so the
loop runs in tests without a live server. Weekend 2 replaces the shim with
a real MCP client over Streamable HTTP; the node code must not change,
only the transport underneath it.
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from visiontriage.mcp_server import _stub_analyze
from visiontriage.schemas import Detection, TriageReport

CONFIDENCE_FLOOR = 0.5


class TriageState(TypedDict, total=False):
    image_id: str
    detections: list[Detection]
    tool_calls: list[str]
    diagnosis: str
    report: TriageReport


def _call_analyze(image_id: str) -> list[Detection]:
    """Transport shim: in-process today, MCP over HTTP from Weekend 2."""
    return _stub_analyze(image_id)


def investigate(state: TriageState) -> TriageState:
    detections = _call_analyze(state["image_id"])
    return {
        "detections": detections,
        "tool_calls": [*state.get("tool_calls", []), "analyze_image"],
    }


def diagnose(state: TriageState) -> TriageState:
    top = max(state["detections"], key=lambda d: d.score)
    if top.label == "none" or top.score < CONFIDENCE_FLOOR:
        text = f"No significant anomaly detected (top score {top.score:.2f})."
    else:
        text = (
            f"Likely {top.label} defect with confidence {top.score:.2f}; "
            "above the triage floor, human review recommended."
        )
    return {"diagnosis": text}


def report(state: TriageState) -> TriageState:
    top = max(state["detections"], key=lambda d: d.score)
    if top.label == "none" or top.score < CONFIDENCE_FLOOR:
        verdict = "normal"
    else:
        verdict = "anomaly"
    return {
        "report": TriageReport(
            image_id=state["image_id"],
            verdict=verdict,
            detections=state["detections"],
            diagnosis=state["diagnosis"],
            tool_calls=state.get("tool_calls", []),
        )
    }


def build_graph():
    builder = StateGraph(TriageState)
    builder.add_node("investigate", investigate)
    builder.add_node("diagnose", diagnose)
    builder.add_node("report", report)
    builder.add_edge(START, "investigate")
    builder.add_edge("investigate", "diagnose")
    builder.add_edge("diagnose", "report")
    builder.add_edge("report", END)
    return builder.compile()


def triage(image_id: str) -> TriageReport:
    """Run one image through the graph and return the final report."""
    result = build_graph().invoke({"image_id": image_id, "tool_calls": []})
    return result["report"]


if __name__ == "__main__":
    for sample in ("defect_bottle_001", "good_bottle_014"):
        print(triage(sample).model_dump_json(indent=2))
