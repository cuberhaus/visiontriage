"""LangGraph analyst loop: profile -> plan -> tools -> synthesise -> validate
-> human approval (interrupt) -> finalize/filing.

Code owns numbers and validation; the Analyst only proposes queries and
drafts findings. Budgets: <=3 planning rounds, <=12 tool calls, <=2 retries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from visiontriage import tools
from visiontriage.analysts import TOOL_ALLOWLIST, ProfilerAnalyst
from visiontriage.bundle import Bundle, load_bundle
from visiontriage.filing import GhFiler
from visiontriage.mcp_client import call_tool as mcp_call
from visiontriage.prompt_loader import prompt_versions
from visiontriage.profiler import compute_profile
from visiontriage.report import render_report
from visiontriage.schemas import FindingsDocument, Inspection
from visiontriage.validator import validate_findings

MAX_ROUNDS = 3
MAX_TOOL_CALLS = 12
MAX_RETRIES = 2
MAX_INSPECT_CALLS = 2


class AgentState(TypedDict, total=False):
    bundle_dir: str
    output_dir: str
    profile: dict
    rounds: int
    tool_calls: list[dict]
    tool_results: list[dict]
    pending_queries: list[dict]
    plan_done: bool
    inspections: list[dict]
    draft_findings: list[dict]
    findings: list[dict]
    validation_errors: list[str]
    should_retry: bool
    synth_attempts: int
    investigation_complete: bool
    used_fallback: bool
    decision: dict
    filed: list[dict]
    status: str


def _local_tool(bundle: Bundle, tool: str, args: dict) -> dict:
    fn = getattr(tools, tool)
    return fn(bundle, **args)


def build_graph(bundle: Bundle, analyst, output_dir: Path,
                tool_caller=None, filer: GhFiler | None = None,
                repo: str | None = None, file_issues: bool = False):
    output_dir.mkdir(parents=True, exist_ok=True)
    fallback = ProfilerAnalyst()
    state_fallback = {"active": False}

    def active_analyst():
        return fallback if state_fallback["active"] else analyst

    def call(tool: str, args: dict) -> dict:
        if tool_caller is not None:
            return tool_caller(bundle, tool, args)
        return mcp_call(str(bundle.root), tool, args)

    def profile_node(state: AgentState) -> AgentState:
        profile = compute_profile(bundle)
        (output_dir / "profile.json").write_text(json.dumps(profile, indent=2))
        return {"profile": profile, "rounds": 0, "tool_calls": [],
                "tool_results": [], "inspections": [], "synth_attempts": 0,
                "investigation_complete": True, "used_fallback": False}

    def plan_node(state: AgentState) -> AgentState:
        rounds = state.get("rounds", 0)
        if rounds >= MAX_ROUNDS or len(state.get("tool_calls", [])) >= MAX_TOOL_CALLS:
            return {"plan_done": True, "pending_queries": []}
        try:
            plan = active_analyst().plan(state["profile"], state.get("tool_results", []))
        except Exception:
            if state.get("tool_results"):
                # A late planning failure (e.g. a malformed repeat round)
                # ends planning; synthesis still gets the collected evidence.
                return {"plan_done": True, "pending_queries": []}
            state_fallback["active"] = True
            plan = fallback.plan(state["profile"], state.get("tool_results", []))
            return {"plan_done": False, "used_fallback": True,
                    "pending_queries": plan.get("queries", []), "rounds": rounds + 1}
        if plan.get("done"):
            return {"plan_done": True, "pending_queries": []}
        seen = {(c["tool"], json.dumps(c.get("args", {}), sort_keys=True))
                for c in state.get("tool_calls", [])}
        queries = [q for q in plan.get("queries", [])
                   if (q.get("tool"), json.dumps(q.get("args", {}), sort_keys=True)) not in seen]
        if not queries:
            return {"plan_done": True, "pending_queries": []}
        return {"plan_done": False, "pending_queries": queries,
                "rounds": rounds + 1}

    def tools_node(state: AgentState) -> AgentState:
        calls = list(state.get("tool_calls", []))
        results = list(state.get("tool_results", []))
        inspections = [Inspection.model_validate(i) for i in state.get("inspections", [])]
        inspect_calls = sum(1 for c in calls if c["tool"] == "inspect_examples")
        for query in state.get("pending_queries", []):
            if len(calls) >= MAX_TOOL_CALLS:
                break
            tool, args = query.get("tool"), query.get("args", {})
            if tool not in TOOL_ALLOWLIST:
                continue
            if tool == "inspect_examples":
                if inspect_calls >= MAX_INSPECT_CALLS:
                    continue
                try:
                    # Deterministic selection: worst examples of the slice/cluster.
                    selected = tools.list_examples(
                        bundle, outcome=args.get("outcome", "fn"),
                        dimension=args.get("dimension"), value=args.get("value"), limit=5)
                    ids = [e["image_id"] for e in selected["examples"]][:5]
                    if not ids:
                        continue
                    supplied = call("get_images", {"image_ids": ids})
                    inspection = active_analyst().inspect(
                        f"I{inspect_calls + 1}", supplied["images"])
                except Exception as exc:  # a failed inspection must not kill the run
                    calls.append({"tool": "inspect_examples", "args": args})
                    results.append({"tool": "inspect_examples", "args": args,
                                    "result": {"error": f"{type(exc).__name__}: {exc}"}})
                    inspect_calls += 1
                    continue
                inspections.append(inspection)
                inspect_calls += 1
                calls.append({"tool": "inspect_examples", "args": args})
                results.append({"tool": "inspect_examples", "args": args,
                                "result": inspection.model_dump()})
                continue
            try:
                result = call(tool, args)
            except Exception as exc:  # LLM-proposed bad args etc: record, move on
                result = {"error": f"{type(exc).__name__}: {exc}"}
            calls.append({"tool": tool, "args": args})
            results.append({"tool": tool, "args": args, "result": result})
        return {"tool_calls": calls, "tool_results": results,
                "inspections": [i.model_dump() for i in inspections],
                "pending_queries": []}

    def synth_node(state: AgentState) -> AgentState:
        inspections = [Inspection.model_validate(i) for i in state.get("inspections", [])]
        try:
            findings = active_analyst().synthesize(
                state["profile"], state.get("tool_results", []), inspections,
                state.get("validation_errors", []))
        except Exception:
            state_fallback["active"] = True
            findings = fallback.synthesize(
                state["profile"], state.get("tool_results", []), inspections, [])
            return {"draft_findings": [f.model_dump() for f in findings],
                    "used_fallback": True,
                    "synth_attempts": state.get("synth_attempts", 0) + 1}
        return {"draft_findings": [f.model_dump() for f in findings],
                "synth_attempts": state.get("synth_attempts", 0) + 1}

    def validate_node(state: AgentState) -> AgentState:
        from visiontriage.schemas import Finding
        inspections = [Inspection.model_validate(i) for i in state.get("inspections", [])]
        draft = [Finding.model_validate(f) for f in state.get("draft_findings", [])]
        valid, errors = validate_findings(draft, bundle, inspections)
        attempts = state.get("synth_attempts", 0)
        if errors and len(valid) < len(draft) and attempts <= MAX_RETRIES:
            return {"findings": [f.model_dump() for f in valid],
                    "validation_errors": errors, "should_retry": True}
        if not valid:
            draft2 = fallback.synthesize(state["profile"], state.get("tool_results", []),
                                         inspections, [])
            valid, errors2 = validate_findings(draft2, bundle, inspections)
            return {"findings": [f.model_dump() for f in valid],
                    "validation_errors": errors + errors2, "should_retry": False,
                    "investigation_complete": False,
                    # Falling back is only news when the primary analyst
                    # is not already the profiler baseline itself.
                    "used_fallback": not isinstance(analyst, ProfilerAnalyst)}
        return {"findings": [f.model_dump() for f in valid],
                "validation_errors": errors, "should_retry": False}

    def _doc(state: AgentState) -> FindingsDocument:
        from visiontriage.schemas import Finding
        used_fallback = bool(state.get("used_fallback", False))
        return FindingsDocument(
            run_id=bundle.metadata.run_id,
            model=getattr(analyst, "name", "unknown"),
            prompt_versions=prompt_versions(), git_sha=bundle.metadata.git_sha,
            investigation_complete=bool(
                state.get("investigation_complete", True)) and not used_fallback,
            used_fallback=used_fallback,
            findings=[Finding.model_validate(f) for f in state.get("findings", [])],
            tool_calls=state.get("tool_calls", []),
        )

    def report_node(state: AgentState) -> AgentState:
        doc = _doc(state)
        (output_dir / "findings.json").write_text(doc.model_dump_json(indent=2))
        (output_dir / "report.md").write_text(render_report(doc, state["profile"]))
        (output_dir / "tool_trace.json").write_text(
            json.dumps(state.get("tool_calls", []), indent=2))
        return {"status": "awaiting_approval"}

    def approval_node(state: AgentState) -> AgentState:
        decision = interrupt({
            "run_id": bundle.metadata.run_id,
            "findings": state.get("findings", []),
            "prompt": "Approve the report and select action IDs to file.",
        })
        return {"decision": decision or {}, "status": "decided"}

    def finalize_node(state: AgentState) -> AgentState:
        from visiontriage.schemas import Finding
        decision = state.get("decision", {})
        filed: list[dict] = []
        if decision.get("approved"):
            selected = set(decision.get("selected_action_ids", []))
            active_filer = filer or GhFiler(repo=repo, dry_run=not file_issues)
            for finding in [Finding.model_validate(f) for f in state.get("findings", [])]:
                for action in finding.actions:
                    if action.action_id in selected:
                        filed.append(active_filer.file(bundle.metadata.run_id, finding, action))
        doc = _doc(state)
        (output_dir / "findings.json").write_text(doc.model_dump_json(indent=2))
        (output_dir / "report.md").write_text(render_report(
            doc, state["profile"],
            decisions=json.dumps(decision, indent=2), filed=filed))
        return {"filed": filed,
                "status": "completed" if decision.get("approved") else "rejected"}

    builder = StateGraph(AgentState)
    builder.add_node("profile", profile_node)
    builder.add_node("plan", plan_node)
    builder.add_node("tools", tools_node)
    builder.add_node("synthesise", synth_node)
    builder.add_node("validate", validate_node)
    builder.add_node("report", report_node)
    builder.add_node("approval", approval_node)
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "profile")
    builder.add_edge("profile", "plan")
    builder.add_conditional_edges(
        "plan", lambda s: "synthesise" if s.get("plan_done") else "tools",
        {"tools": "tools", "synthesise": "synthesise"})
    builder.add_conditional_edges(
        "tools",
        lambda s: "synthesise" if (s.get("rounds", 0) >= MAX_ROUNDS
                                   or len(s.get("tool_calls", [])) >= MAX_TOOL_CALLS)
        else "plan",
        {"plan": "plan", "synthesise": "synthesise"})
    builder.add_edge("synthesise", "validate")
    builder.add_conditional_edges(
        "validate", lambda s: "synthesise" if s.get("should_retry") else "report",
        {"synthesise": "synthesise", "report": "report"})
    builder.add_edge("report", "approval")
    builder.add_edge("approval", "finalize")
    builder.add_edge("finalize", END)
    return builder


def analyse(bundle_dir: str, analyst, output_root: str | Path = "analysis",
            db_path: str | Path = ".visiontriage/analyses.db", thread_id: str | None = None,
            tool_caller=None, filer: GhFiler | None = None,
            repo: str | None = None, file_issues: bool = False,
            decision: dict | None = None):
    """Run (or resume) one analysis. Returns the graph result dict."""
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command

    bundle = load_bundle(bundle_dir)
    output_dir = Path(output_root) / bundle.metadata.run_id
    builder = build_graph(bundle, analyst, output_dir, tool_caller=tool_caller,
                          filer=filer, repo=repo, file_issues=file_issues)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(db_path)) as saver:
        graph = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": thread_id or bundle.metadata.run_id}}
        if decision is not None:
            return graph.invoke(Command(resume=decision), config)
        return graph.invoke(
            {"bundle_dir": str(bundle_dir), "output_dir": str(output_dir)}, config)
