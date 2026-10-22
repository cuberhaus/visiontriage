"""GitHub issue filing for approved Recommended Actions.

Dry-run by default; real filing needs an explicit --repo and approval.
"""

from __future__ import annotations

import json
import subprocess

from visiontriage.schemas import Finding


def marker(run_id: str, finding_id: str) -> str:
    return f"visiontriage:run={run_id}:finding={finding_id}"


def issue_body(run_id: str, finding: Finding, action) -> str:
    return (
        f"{action.body}\n\n"
        f"Finding: {finding.title} (`{finding.taxonomy}`)\n"
        f"Supporting metric: {finding.metric_name} = {finding.metric_value}\n"
        f"Evidence examples: {', '.join(finding.evidence_image_ids)}\n\n"
        f"<!-- {marker(run_id, finding.finding_id)} -->\n"
    )


class GhFiler:
    def __init__(self, repo: str | None, dry_run: bool = True):
        self.repo = repo
        self.dry_run = dry_run

    def _gh(self, *args: str) -> str:
        return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout

    def file(self, run_id: str, finding: Finding, action) -> dict:
        mark = marker(run_id, finding.finding_id)
        record = {"action_id": action.action_id, "finding_id": finding.finding_id, "marker": mark}
        if self.dry_run or not self.repo:
            return record | {"status": "dry-run", "title": action.title}
        existing = self._gh("issue", "list", "--repo", self.repo, "--state", "open",
                            "--search", mark, "--json", "url", "--jq", ".[0].url // \"\"").strip()
        if existing:
            return record | {"status": "already-filed", "url": existing}
        url = self._gh("issue", "create", "--repo", self.repo, "--title", action.title,
                       "--body", issue_body(run_id, finding, action)).strip()
        return record | {"status": "filed", "url": url}


def plan_filings(run_id: str, findings: list[Finding], selected_action_ids: set[str]) -> list[dict]:
    """Dry-run view of what would be filed for the selected actions."""
    out = []
    for finding in findings:
        for action in finding.actions:
            if action.action_id in selected_action_ids:
                out.append({
                    "action_id": action.action_id, "finding_id": finding.finding_id,
                    "marker": marker(run_id, finding.finding_id),
                    "status": "dry-run", "title": action.title,
                    "body": issue_body(run_id, finding, action),
                })
    return out
