"""MCP server (stdio) exposing investigation tools over one Run Bundle.

Launched scoped to a single bundle; the bundle root is the sandbox.
Run:  python -m visiontriage.tools_server <bundle_dir>
"""

from __future__ import annotations

import os
import sys

from fastmcp import FastMCP

from visiontriage import tools
from visiontriage.bundle import load_bundle

_bundle_dir = os.environ.get("VISIONTRIAGE_BUNDLE") or (sys.argv[1] if len(sys.argv) > 1 else ".")
bundle = load_bundle(_bundle_dir)

mcp = FastMCP("visiontriage-tools")


@mcp.tool
def slice_metrics(dimension: str, value: str) -> dict:
    """Metrics for one slice, e.g. dimension='category', value='screw'."""
    return tools.slice_metrics(bundle, dimension, value)


@mcp.tool
def list_examples(outcome: str = "fn", dimension: str | None = None,
                  value: str | None = None, limit: int = 10) -> dict:
    """List examples by outcome (fp/fn/tp/tn/all), worst mistakes first."""
    return tools.list_examples(bundle, outcome, dimension, value, limit)


@mcp.tool
def cluster_failures(outcome: str = "fn", similarity: float = 0.9) -> dict:
    """Cluster false positives/negatives by embedding similarity."""
    return tools.cluster_failures(bundle, outcome, similarity)


@mcp.tool
def duplicate_check() -> dict:
    """Near-duplicate embeddings shared across splits (leakage signal)."""
    return tools.duplicate_check(bundle)


@mcp.tool
def quality_breakdown() -> dict:
    """Error breakdown by image-quality band (dark/normal/bright)."""
    return tools.quality_breakdown(bundle)


@mcp.tool
def score_distribution(bins: int = 10) -> dict:
    """Score histogram with anomaly and error counts per bin."""
    return tools.score_distribution(bundle, bins)


@mcp.tool
def get_images(image_ids: list[str]) -> dict:
    """Return base64 image bytes for up to 5 bundle images, for inspection."""
    return tools.get_images(bundle, image_ids)


if __name__ == "__main__":
    mcp.run(transport="stdio")
