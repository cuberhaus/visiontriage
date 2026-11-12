"""Bridge from sync agent code to the FastMCP stdio tool server."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


async def _call(bundle_dir: str, tool: str, args: dict):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "visiontriage.tools_server", str(Path(bundle_dir).resolve())],
    )
    async with Client(transport) as client:
        result = await client.call_tool(tool, args)
        return result.data


def call_tool(bundle_dir: str, tool: str, args: dict) -> dict:
    return asyncio.run(_call(bundle_dir, tool, args))
