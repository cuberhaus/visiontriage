"""Analyst implementations.

An Analyst plans tool queries, inspects images, and synthesises Findings.
Three implementations:
- ProfilerAnalyst: deterministic baseline (no LLM). The sweep baseline.
- FakeAnalyst: rule-driven stand-in used in CI (scripted, no model).
- OllamaAnalyst: one local multimodal model in three call modes.
"""

from __future__ import annotations

import base64
import json
import urllib.request

from visiontriage.prompt_loader import load_prompt, prompt_versions
from visiontriage.schemas import Finding, Inspection, RecommendedAction

TOOL_ALLOWLIST = {
    "slice_metrics", "list_examples", "cluster_failures",
    "quality_breakdown", "score_distribution", "inspect_examples", "duplicate_check",
}


def _finding_from_candidate(idx: int, cand: dict, evidence: list[str]) -> Finding:
    dim, value = cand["dimension"], cand["value"]
    taxonomy = "quality_confound" if dim == "quality_band" else "slice_weakness"
    action_category = "report_quality_slice" if dim == "quality_band" else "collect_data"
    return Finding(
        finding_id=f"F{idx}", title=f"Elevated errors in {dim}={value}",
        taxonomy=taxonomy,  # type: ignore[arg-type]
        summary=f"The {dim} slice '{value}' shows error rate {cand['error_rate']} "
                f"across {cand['support']} predictions.",
        slice_dimension=dim, slice_value=value,
        evidence_image_ids=evidence[:5],
        metric_name="error_rate", metric_value=cand["error_rate"],
        actions=[RecommendedAction(
            action_id=f"A{idx}", category=action_category,
            title=f"Investigate {dim}={value} failures",
            body=f"Review the {dim}={value} slice (error rate {cand['error_rate']}).")],
    )


class ProfilerAnalyst:
    """Deterministic baseline: plans a look at the worst candidate slice."""

    name = "profiler"

    def plan(self, profile: dict, history: list[dict]) -> dict:
        if history:
            return {"done": True}
        if not profile["candidates"]:
            return {"done": True}
        top = profile["candidates"][0]
        # Ask for the error kind this slice actually has (FP-heavy slices
        # have no false negatives to cite as evidence).
        outcome = "fp" if top.get("fp", 0) > top.get("fn", 0) else "fn"
        return {"queries": [
            {"tool": "slice_metrics", "args": {"dimension": top["dimension"], "value": top["value"]}},
            {"tool": "list_examples", "args": {"outcome": outcome, "dimension": top["dimension"],
                                               "value": top["value"], "limit": 5}},
        ]}

    def inspect(self, inspection_id: str, images: list[dict]) -> Inspection:
        return Inspection(inspection_id=inspection_id,
                          image_ids=[i["image_id"] for i in images],
                          observations=[{"image_id": i["image_id"],
                                         "description": "not inspected (profiler mode)",
                                         "quality": "unknown", "confidence": 0.0}
                                        for i in images])

    def synthesize(self, profile: dict, tool_results: list[dict],
                   inspections: list[Inspection], errors: list[str]) -> list[Finding]:
        findings: list[Finding] = []
        examples: list[str] = []
        for result in tool_results:
            if result.get("tool") == "list_examples":
                for example in result["result"].get("examples", []):
                    if example["image_id"] not in examples:
                        examples.append(example["image_id"])
        for i, cand in enumerate(profile["candidates"][:3], 1):
            findings.append(_finding_from_candidate(i, cand, examples))
        return findings


class FakeAnalyst(ProfilerAnalyst):
    """Scripted CI analyst: same behaviour as the baseline, via the full loop."""

    name = "fake"


class OllamaAnalyst:
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434"):
        self.model = model
        self.name = model
        self.base_url = base_url.rstrip("/")

    def _chat(self, prompt_name: str, payload: dict, images: list[str] | None = None) -> dict:
        body, _version = load_prompt(prompt_name)
        message: dict = {"role": "user", "content": body + "\n\n" + json.dumps(payload)}
        if images:
            message["images"] = images
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps({
                "model": self.model, "stream": False, "format": "json",
                # Thinking models otherwise spend minutes reasoning before
                # the JSON; with think off this Ollama build still returns
                # the reply in the `thinking` field, so accept either.
                "think": False,
                "options": {"temperature": 0},
                "messages": [message],
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            data = json.loads(response.read())
        message_out = data.get("message") or {}
        raw = message_out.get("content") or message_out.get("thinking") or ""
        if not raw.strip():
            raise ValueError("empty response from Ollama")
        return json.loads(raw)

    def plan(self, profile: dict, history: list[dict]) -> dict:
        result = self._chat("plan", {"profile": profile, "history": history})
        queries = [q for q in result.get("queries", [])
                   if q.get("tool") in TOOL_ALLOWLIST]
        if result.get("done") or not queries:
            return {"done": True}
        return {"queries": queries}

    def inspect(self, inspection_id: str, images: list[dict]) -> Inspection:
        encoded = [i["image_base64"] for i in images if i.get("image_base64")]
        payload = {"image_ids": [i["image_id"] for i in images]}
        try:
            result = self._chat("inspect", payload, images=encoded)
            observations = result.get("observations", [])
        except Exception as exc:  # vision call failed: record, do not invent
            observations = [{"image_id": i["image_id"], "description": f"inspection failed: {exc}",
                             "quality": "unknown", "confidence": 0.0} for i in images]
        return Inspection(inspection_id=inspection_id,
                          image_ids=[i["image_id"] for i in images],
                          observations=observations)

    def synthesize(self, profile: dict, tool_results: list[dict],
                   inspections: list[Inspection], errors: list[str]) -> list[Finding]:
        payload = {
            "profile": profile, "tool_results": tool_results,
            "inspections": [i.model_dump() for i in inspections],
            "validator_errors": errors,
            "prompt_versions": prompt_versions(),
        }
        result = self._chat("synthesize", payload)
        return [Finding.model_validate(f) for f in result.get("findings", [])]


def image_bytes_b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()
