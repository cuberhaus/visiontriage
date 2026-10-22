"""Versioned prompt loading. Prompt text lives in .md files, not code."""

from __future__ import annotations

import re
from importlib import resources


def load_prompt(name: str) -> tuple[str, str]:
    """Return (body, version) for a packaged prompt."""
    text = resources.files("visiontriage.prompts").joinpath(f"{name}.md").read_text()
    match = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        raise ValueError(f"prompt {name} is missing version frontmatter")
    frontmatter, body = match.groups()
    version = re.search(r"version:\s*(\S+)", frontmatter)
    if not version:
        raise ValueError(f"prompt {name} is missing a version")
    return body.strip(), version.group(1)


def prompt_versions() -> dict[str, str]:
    return {name: load_prompt(name)[1] for name in ("plan", "inspect", "synthesize")}
