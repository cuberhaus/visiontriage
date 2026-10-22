"""VisionTriage CLI: profile, analyse, resume."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from visiontriage.bundle import BundleError, load_bundle
from visiontriage.profiler import compute_profile


def _cmd_profile(args) -> int:
    bundle = load_bundle(args.bundle)
    profile = compute_profile(bundle)
    out = Path(args.output) if args.output else Path("analysis") / bundle.metadata.run_id / "profile.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, indent=2))
    print(f"profile written to {out} (overall F1 {profile['overall']['f1']})")
    return 0


def _make_analyst(args):
    if getattr(args, "profiler_only", False):
        from visiontriage.analysts import ProfilerAnalyst
        return ProfilerAnalyst()
    if getattr(args, "fake_analyst", False):
        from visiontriage.analysts import FakeAnalyst
        return FakeAnalyst()
    from visiontriage.analysts import OllamaAnalyst
    model = getattr(args, "model", None) or os.environ.get(
        "VISIONTRIAGE_MODEL", "ollama:qwen3-vl:8b")
    if model.startswith("ollama:"):
        model = model.split(":", 1)[1]
    return OllamaAnalyst(model=model,
                         base_url=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))


def _prompt_decision(findings: list[dict]) -> dict:
    print("\nFindings:")
    action_ids: list[str] = []
    for finding in findings:
        print(f"- {finding['finding_id']}: {finding['title']} [{finding['taxonomy']}]")
        for action in finding.get("actions", []):
            action_ids.append(action["action_id"])
            print(f"    [{action['action_id']}] {action['title']}")
    answer = input("Approve report? [y/N] ").strip().lower()
    if answer != "y":
        return {"approved": False, "selected_action_ids": [], "reviewer": None}
    raw = input(f"Action IDs to file (comma-separated, or 'all') {action_ids}: ").strip()
    selected = action_ids if raw == "all" else [a.strip() for a in raw.split(",") if a.strip()]
    reviewer = input("Reviewer name (optional): ").strip() or None
    return {"approved": True, "selected_action_ids": selected, "reviewer": reviewer}


def _run_analysis(args, decision: dict | None = None) -> int:
    from visiontriage.agent import analyse
    analyst = _make_analyst(args)
    kwargs = dict(
        output_root=args.output_root, db_path=args.db,
        thread_id=getattr(args, "thread_id", None),
        repo=getattr(args, "repo", None), file_issues=getattr(args, "file_issues", False),
    )
    result = analyse(args.bundle, analyst, decision=decision, **kwargs)
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if interrupts and decision is None:
        payload = interrupts[0].value
        run_id = payload["run_id"]
        print(f"Analysis {run_id} is awaiting approval.")
        print(f"Report: {Path(args.output_root) / run_id / 'report.md'}")
        if getattr(args, "yes", False):
            decision = {"approved": True,
                        "selected_action_ids": [
                            a["action_id"] for f in payload["findings"]
                            for a in f.get("actions", [])],
                        "reviewer": None}
        elif getattr(args, "no_prompt", False):
            print(f"Resume with: visiontriage resume {args.bundle} "
                  f"--output-root {args.output_root} --db {args.db}")
            return 0
        else:
            decision = _prompt_decision(payload["findings"])
        result = analyse(args.bundle, analyst, decision=decision, **kwargs)
    status = result.get("status", "completed") if isinstance(result, dict) else "completed"
    print(f"Analysis finished with status: {status}")
    return 0


def _cmd_analyse(args) -> int:
    return _run_analysis(args)


def _cmd_resume(args) -> int:
    # Resume re-enters the same checkpoint thread and prompts for a decision.
    # Usage: visiontriage resume <bundle> [--thread-id <analysis_id>]
    args.no_prompt = False
    args.yes = False
    from visiontriage.agent import analyse
    if not (Path(args.bundle) / "run.json").is_file():
        print(f"error: {args.bundle!r} is not a Run Bundle directory; "
              "resume takes the bundle path (the analysis is identified by "
              "--thread-id, defaulting to the run_id)", file=sys.stderr)
        return 1
    analyst = _make_analyst(args)
    bundle = load_bundle(args.bundle)
    findings_file = Path(args.output_root) / bundle.metadata.run_id / "findings.json"
    if not findings_file.is_file():
        print(f"error: no pending analysis for run {bundle.metadata.run_id} "
              f"under {args.output_root}; run `visiontriage analyse` first",
              file=sys.stderr)
        return 1
    print(f"Resuming analysis for run {bundle.metadata.run_id}; "
          "approve/reject the pending draft.")
    findings = json.loads(findings_file.read_text()).get("findings", [])
    decision = _prompt_decision(findings)
    result = analyse(args.bundle, analyst, output_root=args.output_root,
                     db_path=args.db, thread_id=args.thread_id,
                     repo=args.repo, file_issues=args.file_issues, decision=decision)
    print(f"Analysis finished with status: {result.get('status', 'completed')}")
    return 0


def _cmd_fixture(args) -> int:
    from visiontriage.fixtures import build_fixture, build_visual_benchmark
    if args.visual_benchmark:
        cases = build_visual_benchmark(args.out)
        print(f"visual benchmark written to {args.out} ({len(cases)} cases)")
    else:
        build_fixture(args.scenario, args.out, seed=args.seed)
        print(f"fixture {args.scenario} written to {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="visiontriage")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("profile", help="Profiler only: write profile.json")
    p.add_argument("bundle")
    p.add_argument("--output")
    p.set_defaults(fn=_cmd_profile)

    def add_analysis_args(sp):
        sp.add_argument("bundle")
        sp.add_argument("--model")
        sp.add_argument("--fake-analyst", action="store_true")
        sp.add_argument("--profiler-only", action="store_true")
        sp.add_argument("--output-root", default="analysis")
        sp.add_argument("--db", default=".visiontriage/analyses.db")
        sp.add_argument("--thread-id")
        sp.add_argument("--repo")
        sp.add_argument("--file-issues", action="store_true")

    a = sub.add_parser("analyse", aliases=["analyze"], help="Analyse a Run Bundle")
    add_analysis_args(a)
    a.add_argument("--yes", action="store_true", help="Approve all actions without prompting")
    a.add_argument("--no-prompt", action="store_true", help="Stop at approval and exit")
    a.set_defaults(fn=_cmd_analyse)

    r = sub.add_parser(
        "resume",
        help="Resume a pending approval: resume <bundle> [--thread-id <analysis_id>]")
    add_analysis_args(r)
    r.set_defaults(fn=_cmd_resume)

    f = sub.add_parser("build-fixture", help="Generate a planted fixture bundle")
    f.add_argument("scenario")
    f.add_argument("out")
    f.add_argument("--seed", type=int, default=7)
    f.add_argument("--visual-benchmark", action="store_true")
    f.set_defaults(fn=_cmd_fixture)

    args = parser.parse_args(argv)
    if getattr(args, "file_issues", False) and not getattr(args, "repo", None):
        print("error: --file-issues requires an explicit --repo owner/name",
              file=sys.stderr)
        return 1
    try:
        return args.fn(args)
    except BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
