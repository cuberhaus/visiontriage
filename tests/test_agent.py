import json
from pathlib import Path

from visiontriage.agent import analyse
from visiontriage.analysts import FakeAnalyst, ProfilerAnalyst
from visiontriage.bundle import load_bundle
from visiontriage.filing import GhFiler, marker, plan_filings
from visiontriage.fixtures import build_fixture
from visiontriage.schemas import Finding, RecommendedAction
from visiontriage.validator import validate_findings


def test_cli_seam_fake_analyst_end_to_end(tmp_path):
    bundle_dir = build_fixture("slice_weakness", tmp_path / "fx")
    result = analyse(str(bundle_dir), FakeAnalyst(), output_root=tmp_path / "out",
                     db_path=tmp_path / "state.db", thread_id="t1")
    assert result.get("__interrupt__")
    out = tmp_path / "out" / "fixture-slice_weakness"
    assert (out / "profile.json").is_file()
    doc = json.loads((out / "findings.json").read_text())
    assert doc["findings"]
    result = analyse(str(bundle_dir), FakeAnalyst(), output_root=tmp_path / "out",
                     db_path=tmp_path / "state.db", thread_id="t1",
                     decision={"approved": True,
                               "selected_action_ids": [doc["findings"][0]["actions"][0]["action_id"]],
                               "reviewer": "tester"})
    assert result["status"] == "completed"
    assert "Filed issues" in (out / "report.md").read_text()


def test_profiler_fallback_findings_validate(tmp_path):
    bundle_dir = build_fixture("quality_confound", tmp_path / "fx")
    bundle = load_bundle(bundle_dir)
    analyst = ProfilerAnalyst()
    findings = analyst.synthesize(
        {"candidates": [{"dimension": "quality_band", "value": "dark",
                         "support": 20, "error_rate": 0.5}]},
        [{"tool": "list_examples", "result": {"examples": [
            {"image_id": bundle.predictions[0].image_id},
            {"image_id": bundle.predictions[1].image_id}]}}],
        [], [])
    valid, errors = validate_findings(findings, bundle, [])
    assert valid and not errors


def test_validator_rejects_uncited_visual_claim(tmp_path):
    bundle = load_bundle(build_fixture("slice_weakness", tmp_path / "fx"))
    ids = [p.image_id for p in bundle.predictions[:2]]
    finding = Finding(
        finding_id="F1", title="x", taxonomy="slice_weakness",
        summary="The failures look like dark scratch marks.",
        evidence_image_ids=ids, metric_name="error_rate", metric_value=0.5,
        actions=[RecommendedAction(action_id="A1", category="collect_data",
                                   title="t", body="b")])
    valid, errors = validate_findings([finding], bundle, [])
    assert not valid and any("visual claim" in e for e in errors)


def test_filing_dry_run_and_marker(tmp_path):
    bundle = load_bundle(build_fixture("slice_weakness", tmp_path / "fx"))
    finding = Finding(
        finding_id="F1", title="x", taxonomy="slice_weakness", summary="s",
        evidence_image_ids=[p.image_id for p in bundle.predictions[:2]],
        metric_name="error_rate", metric_value=0.5,
        actions=[RecommendedAction(action_id="A1", category="collect_data",
                                   title="Do thing", body="Body")])
    planned = plan_filings("run1", [finding], {"A1"})
    assert planned[0]["status"] == "dry-run"
    assert marker("run1", "F1") in planned[0]["body"]
    record = GhFiler(repo=None, dry_run=True).file("run1", finding, finding.actions[0])
    assert record["status"] == "dry-run"


def test_prompt_versions_present():
    from visiontriage.prompt_loader import prompt_versions
    versions = prompt_versions()
    assert set(versions) == {"plan", "inspect", "synthesize"}
    assert all(versions.values())


# Prompt bodies are pinned to their versions: editing a prompt without
# bumping `version:` (and updating this pin) fails this test.
_PROMPT_PINS = {
    "plan": ("1", "741701b7130074835a6a9379d49eafce2dcbc7faca6454c7eebfd249e0d67348"),
    "inspect": ("1", "317d9d1adb6fbe7c30d46eaac0486458d411009ecce9ac4d9b6959f441d4fbcf"),
    "synthesize": ("1", "9a3c9a7346a37aacf75fe52fa0f27b7383e280fa2f70446658b97515d7fbc2ff"),
}


def test_prompt_content_pinned_to_version():
    import hashlib

    from visiontriage.prompt_loader import load_prompt
    for name, (version, digest) in _PROMPT_PINS.items():
        body, actual_version = load_prompt(name)
        assert actual_version == version, f"{name}: bump version when content changes"
        assert hashlib.sha256(body.encode()).hexdigest() == digest, (
            f"{name}: content changed without a version bump")


def test_budget_and_allowlist_enforced(tmp_path):
    from visiontriage import tools

    class GreedyAnalyst(ProfilerAnalyst):
        name = "greedy"

        def plan(self, profile, history):
            queries = [{"tool": "slice_metrics",
                        "args": {"dimension": "category", "value": "screw"}}] * 5
            queries.append({"tool": "list_examples", "args": {"outcome": "fn", "limit": 5}})
            queries.append({"tool": "evil_tool", "args": {}})
            return {"queries": queries}

    bundle_dir = build_fixture("slice_weakness", tmp_path / "fx")

    def local_caller(bundle, tool, args):
        return getattr(tools, tool)(bundle, **args)

    result = analyse(str(bundle_dir), GreedyAnalyst(), output_root=tmp_path / "out",
                     db_path=tmp_path / "state.db", thread_id="greedy",
                     tool_caller=local_caller)
    assert result.get("__interrupt__")
    doc = json.loads((tmp_path / "out" / "fixture-slice_weakness" / "findings.json").read_text())
    assert 0 < len(doc["tool_calls"]) <= 12
    assert all(c["tool"] != "evil_tool" for c in doc["tool_calls"])


def test_ollama_chat_accepts_thinking_field_and_disables_think():
    import io
    import urllib.request

    from visiontriage.analysts import OllamaAnalyst

    captured = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data)
        payload = {"message": {"content": "", "thinking": '{"done": true}'}}
        return FakeResponse(json.dumps(payload).encode())

    original = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        result = OllamaAnalyst(model="m")._chat("plan", {"x": 1})
    finally:
        urllib.request.urlopen = original
    assert result == {"done": True}
    assert captured["body"]["think"] is False


def test_bad_tool_args_do_not_kill_the_run(tmp_path):
    from visiontriage import tools

    class BadArgsAnalyst(ProfilerAnalyst):
        name = "bad-args"

        def plan(self, profile, history):
            if history:
                return {"done": True}
            return {"queries": [
                {"tool": "slice_metrics", "args": {"dimension": "nope", "value": "x"}},
                {"tool": "cluster_failures", "args": {"bogus": 1}},
            ]}

    def local_caller(bundle, tool, args):
        return getattr(tools, tool)(bundle, **args)

    bundle_dir = build_fixture("slice_weakness", tmp_path / "fx")
    result = analyse(str(bundle_dir), BadArgsAnalyst(), output_root=tmp_path / "out",
                     db_path=tmp_path / "state.db", thread_id="bad",
                     tool_caller=local_caller)
    assert result.get("__interrupt__")
    trace = json.loads(
        (tmp_path / "out" / "fixture-slice_weakness" / "tool_trace.json").read_text())
    assert len(trace) == 2  # both bad calls recorded, run survived


def test_profiler_on_leakage_reports_incomplete_honestly(tmp_path):
    """A run with no errors yields no findings, not invented ones."""
    from visiontriage import tools

    def local_caller(bundle, tool, args):
        return getattr(tools, tool)(bundle, **args)

    bundle_dir = build_fixture("leakage", tmp_path / "fx")
    result = analyse(str(bundle_dir), ProfilerAnalyst(), output_root=tmp_path / "out",
                     db_path=tmp_path / "state.db", thread_id="leak",
                     tool_caller=local_caller)
    assert result.get("__interrupt__")
    out = tmp_path / "out" / "fixture-leakage"
    doc = json.loads((out / "findings.json").read_text())
    assert doc["findings"] == []
    assert doc["investigation_complete"] is False
    assert doc["used_fallback"] is False
    report = (out / "report.md").read_text()
    assert "investigation incomplete" in report
    assert "LLM analyst unavailable" not in report


def test_filing_dedupe_skips_existing_issue(tmp_path):
    bundle = load_bundle(build_fixture("slice_weakness", tmp_path / "fx"))
    finding = Finding(
        finding_id="F1", title="x", taxonomy="slice_weakness", summary="s",
        evidence_image_ids=[p.image_id for p in bundle.predictions[:2]],
        metric_name="error_rate", metric_value=0.5,
        actions=[RecommendedAction(action_id="A1", category="collect_data",
                                   title="Do thing", body="Body")])
    filer = GhFiler(repo="owner/repo", dry_run=False)
    calls = []

    def fake_gh(*args):
        calls.append(args)
        return "https://github.com/owner/repo/issues/1\n"

    filer._gh = fake_gh  # type: ignore[method-assign]
    record = filer.file("run1", finding, finding.actions[0])
    assert record["status"] == "already-filed"
    assert record["url"] == "https://github.com/owner/repo/issues/1"
    assert len(calls) == 1  # searched for the marker, never created
