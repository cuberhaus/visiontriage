"""CLI seam: the public `visiontriage` entry point via subprocess.

Covers the Weekend 2 exit criterion: a planted fixture analysed
end-to-end into a validated report with per-action approval and
dry-run filing, resumable approval, and the Ollama-down fallback.
No Ollama and no network are needed (fake / profiler analysts, and a
deliberately dead Ollama URL for the fallback case).
"""

import json
import os
import subprocess
import sys

from visiontriage.fixtures import build_fixture

RUN_ID = "fixture-slice_weakness"


def run_cli(args, *, input_text=None, env_extra=None, cwd=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "visiontriage.cli", *[str(a) for a in args]],
        input=input_text, capture_output=True, text=True, timeout=180,
        env=env, cwd=cwd,
    )


def test_cli_analyse_then_resume(tmp_path):
    fx = tmp_path / "fx"
    proc = run_cli(["build-fixture", "slice_weakness", fx], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr

    profile_out = tmp_path / "profile.json"
    proc = run_cli(["profile", fx, "--output", profile_out], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(profile_out.read_text())["overall"]["support"] > 0

    out, db = tmp_path / "out", tmp_path / "state.db"
    proc = run_cli(["analyse", fx, "--fake-analyst", "--no-prompt",
                    "--output-root", out, "--db", db], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "awaiting approval" in proc.stdout
    # The printed resume hint must be a command that actually works.
    assert f"visiontriage resume {fx}" in proc.stdout
    assert "--bundle" not in proc.stdout

    analysis_dir = out / RUN_ID
    for artefact in ("profile.json", "findings.json", "report.md", "tool_trace.json"):
        assert (analysis_dir / artefact).is_file(), artefact
    doc = json.loads((analysis_dir / "findings.json").read_text())
    assert doc["findings"]
    assert doc["prompt_versions"] == {"plan": "2", "inspect": "1", "synthesize": "1"}
    assert "## Findings" in (analysis_dir / "report.md").read_text()

    first_action = doc["findings"][0]["actions"][0]["action_id"]
    proc = run_cli(["resume", fx, "--fake-analyst",
                    "--output-root", out, "--db", db],
                   input_text=f"y\n{first_action}\ntester\n", cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "completed" in proc.stdout
    report = (analysis_dir / "report.md").read_text()
    assert "## Filed issues" in report
    assert "dry-run" in report


def test_cli_ollama_down_falls_back_to_profiler(tmp_path):
    fx = build_fixture("slice_weakness", tmp_path / "fx")
    out, db = tmp_path / "out", tmp_path / "state.db"
    proc = run_cli(["analyse", fx, "--yes", "--output-root", out, "--db", db],
                   env_extra={"OLLAMA_BASE_URL": "http://127.0.0.1:59999"},
                   cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "completed" in proc.stdout
    doc = json.loads((out / RUN_ID / "findings.json").read_text())
    assert doc["findings"], "fallback must never produce an empty report"
    assert doc["used_fallback"] is True
    assert doc["investigation_complete"] is False
    report = (out / RUN_ID / "report.md").read_text()
    assert "profiler-only" in report
    assert "investigation incomplete" in report


def test_cli_profiler_only_is_not_fallback(tmp_path):
    fx = build_fixture("quality_confound", tmp_path / "fx")
    out, db = tmp_path / "out", tmp_path / "state.db"
    proc = run_cli(["analyse", fx, "--profiler-only", "--yes",
                    "--output-root", out, "--db", db], cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr
    run_id = "fixture-quality_confound"
    doc = json.loads((out / run_id / "findings.json").read_text())
    assert doc["findings"]
    assert doc["model"] == "profiler"
    assert doc["used_fallback"] is False
    assert doc["investigation_complete"] is True


def test_cli_resume_without_pending_analysis_fails_cleanly(tmp_path):
    fx = build_fixture("slice_weakness", tmp_path / "fx")
    proc = run_cli(["resume", fx, "--fake-analyst",
                    "--output-root", tmp_path / "out", "--db", tmp_path / "state.db"],
                   input_text="y\nall\n\n", cwd=tmp_path)
    assert proc.returncode == 1
    assert "no pending analysis" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_cli_file_issues_requires_repo(tmp_path):
    fx = build_fixture("slice_weakness", tmp_path / "fx")
    proc = run_cli(["analyse", fx, "--fake-analyst", "--yes", "--file-issues",
                    "--output-root", tmp_path / "out", "--db", tmp_path / "state.db"],
                   cwd=tmp_path)
    assert proc.returncode == 1
    assert "--repo" in proc.stderr
    assert not (tmp_path / "out").exists()


def test_cli_resume_rejects_analysis_id_as_bundle(tmp_path):
    proc = run_cli(["resume", RUN_ID, "--fake-analyst"], cwd=tmp_path)
    assert proc.returncode == 1
    assert "not a Run Bundle" in proc.stderr
    assert "Traceback" not in proc.stderr
