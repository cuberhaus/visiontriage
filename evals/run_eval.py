"""Model sweep runner — local, manual only. Never run in CI.

Builds the six planted fixtures, runs each candidate analyst through
the full agent loop, scores the findings deterministically
(`evals/scorer.py`), and exports a generated results table.

Usage:
  uv run python -m evals.run_eval --candidates profiler,qwen3-vl:8b
  uv run python -m evals.run_eval --candidates profiler,fake --output-dir /tmp/eval-smoke
  uv run python -m evals.run_eval --visual --blind-ratings ratings.json

Candidates: `profiler` and `fake` are built in; any other name is an
Ollama model tag. Disk-tight sweeps pull/run/remove large models one
at a time outside this script (see issue #4).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import time
from pathlib import Path

from evals.scorer import aggregate, score_scenario, score_visual, select_default
from visiontriage.agent import MAX_INSPECT_CALLS, MAX_TOOL_CALLS, analyse
from visiontriage.analysts import FakeAnalyst, OllamaAnalyst, ProfilerAnalyst
from visiontriage.bundle import load_bundle
from visiontriage.fixtures import EXPECTED, SCENARIOS, build_fixture, build_visual_benchmark
from visiontriage.prompt_loader import prompt_versions


def make_analyst(name: str):
    if name == "profiler":
        return ProfilerAnalyst()
    if name == "fake":
        return FakeAnalyst()
    return OllamaAnalyst(
        model=name,
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-")


def _run_visual(analyst, work_root: Path, per_kind: int) -> float:
    bench_dir = work_root / "visual-benchmark"
    cases = build_visual_benchmark(bench_dir, per_kind=per_kind)
    observed = []
    for i, case in enumerate(cases):
        raw = (bench_dir / case["image"]).read_bytes()
        try:
            inspection = analyst.inspect(
                f"V{i}", [{"image_id": case["image"], "path": case["image"],
                           "image_base64": base64.b64encode(raw).decode()}])
            text = " ".join(
                f"{o.get('description', '')} {o.get('quality', '')}"
                for o in inspection.observations)
        except Exception as exc:  # a failed inspection scores as wrong, not fatal
            text = f"inspection failed: {exc}"
        observed.append({**case, "observed_text": text})
    return score_visual(observed)["accuracy"]


def run_sweep(candidate_names: list[str], output_dir: str | Path,
              scenarios: tuple[str, ...] = SCENARIOS, visual: bool = False,
              visual_per_kind: int = 2, tool_caller=None,
              analyst_factory=None, blind_ratings: dict | None = None) -> dict:
    output_dir = Path(output_dir)
    work_root = output_dir / "work"
    bundles = {s: build_fixture(s, work_root / "bundles" / s) for s in scenarios}

    rows: list[dict] = []
    summaries: dict[str, dict] = {}
    for name in candidate_names:
        factory = analyst_factory or make_analyst
        analyst = factory(name)
        candidate_rows: list[dict] = []
        for scenario in scenarios:
            bundle = load_bundle(bundles[scenario])
            started = time.time()
            error = None
            try:
                analyse(str(bundles[scenario]), analyst,
                        output_root=work_root / "runs" / _safe(name),
                        db_path=work_root / f"{_safe(name)}.db",
                        thread_id=bundle.metadata.run_id,
                        tool_caller=tool_caller)
                doc = json.loads((work_root / "runs" / _safe(name)
                                  / bundle.metadata.run_id / "findings.json").read_text())
            except Exception as exc:  # one bad run must not kill the sweep
                doc, error = {"findings": [], "tool_calls": [], "used_fallback": True}, \
                    f"{type(exc).__name__}: {exc}"
            latency = round(time.time() - started, 2)
            row = score_scenario(EXPECTED[scenario], doc.get("findings", []), bundle)
            tool_calls = doc.get("tool_calls", [])
            row.update({
                "candidate": name, "scenario": scenario, "latency_s": latency,
                "structured_ok": error is None and not doc.get("used_fallback", True),
                "budget_ok": (len(tool_calls) <= MAX_TOOL_CALLS and sum(
                    1 for c in tool_calls if c["tool"] == "inspect_examples")
                    <= MAX_INSPECT_CALLS),
                "used_fallback": bool(doc.get("used_fallback")),
                "error": error,
            })
            candidate_rows.append(row)
            rows.append(row)
        summary = aggregate(candidate_rows)
        if visual:
            try:
                summary["visual_accuracy"] = _run_visual(factory(name), work_root,
                                                         visual_per_kind)
            except Exception:
                summary["visual_accuracy"] = 0.0
        if blind_ratings and name in blind_ratings:
            summary["blind_rating"] = blind_ratings[name]
        summaries[name] = summary

    result = {
        "prompt_versions": prompt_versions(),
        "scenarios": list(scenarios),
        "summaries": summaries,
        "rows": rows,
        "selection": select_default(summaries),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(json.dumps(result, indent=2))
    (output_dir / "RESULTS.md").write_text(render_table(result))
    return result


def render_table(result: dict) -> str:
    lines = [
        "# Sweep results (generated by evals/run_eval.py — do not hand-edit)",
        "",
        f"Prompt versions: {result['prompt_versions']}",
        "",
        "| Candidate | F1 | Precision | Recall | Evidence P | Action acc | "
        "Structured | Budget | Fallbacks | Mean latency (s) | Visual acc |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in result["summaries"].items():
        visual_acc = s.get("visual_accuracy")
        lines.append(
            f"| {name} | {s['failure_mode_f1']} | {s['failure_mode_precision']} | "
            f"{s['failure_mode_recall']} | {s['evidence_precision']} | "
            f"{s['action_accuracy']} | {s['structured_success']} | "
            f"{s['budget_compliance']} | {s['fallback_runs']}/{s['scenarios']} | "
            f"{s['mean_latency_s']} | {visual_acc if visual_acc is not None else '—'} |")
    selection = result["selection"]
    lines += [
        "",
        f"**Pre-registered selection: `{selection['default']}`** — {selection['reason']}",
        "",
        f"Eliminated: {selection['eliminated'] or 'none'}",
        f"Visual claims: {selection['visual_status']}",
        "",
        "Blind human usefulness ratings are a human-only input (issue #6); "
        "when absent they do not affect ranking above the latency tiebreak.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the analyst model sweep locally")
    parser.add_argument("--candidates", default="profiler,qwen3-vl:8b",
                        help="Comma-separated: profiler, fake, or Ollama model tags")
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--output-dir", default="evals/results")
    parser.add_argument("--visual", action="store_true",
                        help="Also measure visual-benchmark accuracy per candidate")
    parser.add_argument("--blind-ratings", type=Path,
                        help="JSON file mapping candidate name to blind rating 1-5")
    args = parser.parse_args(argv)
    blind = json.loads(args.blind_ratings.read_text()) if args.blind_ratings else None
    result = run_sweep(
        [c.strip() for c in args.candidates.split(",") if c.strip()],
        args.output_dir,
        scenarios=tuple(s.strip() for s in args.scenarios.split(",") if s.strip()),
        visual=args.visual, blind_ratings=blind)
    print(render_table(result))
    print(f"results written to {args.output_dir}/results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
