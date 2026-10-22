"""Failure Analysis Report rendering (Markdown, deterministic)."""

from __future__ import annotations

from visiontriage.schemas import FindingsDocument


def render_report(doc: FindingsDocument, profile: dict,
                  decisions: dict | None = None, filed: list[dict] | None = None) -> str:
    overall = profile["overall"]
    lines = [
        f"# Failure Analysis Report — {doc.run_id}",
        "",
        f"- Model: `{doc.model}`",
        f"- Profiler model: {profile['model']} on {profile['dataset']} "
        f"(threshold {profile['threshold']})",
        f"- Overall: F1 {overall['f1']}, precision {overall['precision']}, "
        f"recall {overall['recall']}, AUROC {overall['auroc']} "
        f"(TP {overall['tp']}, FP {overall['fp']}, FN {overall['fn']}, TN {overall['tn']})",
        f"- Prompt versions: {doc.prompt_versions}",
        f"- Investigation complete: {doc.investigation_complete}",
    ]
    if doc.used_fallback:
        lines.append(
            "- Note: LLM analyst unavailable or failed; deterministic "
            "profiler-only findings — investigation incomplete.")
    elif not doc.investigation_complete:
        lines.append(
            "- Note: investigation incomplete; see the profiler summary below.")
    lines += [
        "",
        "## Findings",
        "",
    ]
    if not doc.findings:
        lines += ["No validated findings. See the profiler summary below.", ""]
    for finding in doc.findings:
        lines += [
            f"### {finding.finding_id} — {finding.title}",
            "",
            f"- Taxonomy: `{finding.taxonomy}`",
        ]
        if finding.slice_dimension:
            lines.append(f"- Slice: {finding.slice_dimension} = {finding.slice_value}")
        lines += [
            f"- Supporting metric: {finding.metric_name} = {finding.metric_value}",
            f"- Evidence examples: {', '.join(finding.evidence_image_ids)}",
            "",
            finding.summary,
            "",
        ]
        for claim in finding.visual_claims:
            lines.append(f"> Visual claim ({claim.inspection_id}): {claim.text}")
        if finding.visual_claims:
            lines.append("")
        lines.append("**Recommended actions:**")
        for action in finding.actions:
            lines.append(f"- [{action.action_id}] ({action.category}) {action.title}")
        lines.append("")
    if decisions:
        lines += ["## Human decision", "", f"```json\n{decisions}\n```", ""]
    if filed:
        lines += ["## Filed issues", ""]
        for item in filed:
            lines.append(f"- {item.get('action_id')}: {item.get('url') or item.get('status')}")
        lines.append("")
    lines += ["## Profiler candidates", ""]
    for cand in profile["candidates"][:10]:
        lines.append(
            f"- {cand['dimension']}={cand['value']}: error_rate {cand['error_rate']} "
            f"on {cand['support']} predictions ({cand['errors']} errors)")
    lines.append("")
    return "\n".join(lines)
