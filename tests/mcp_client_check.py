"""Talk to Roundtable's MCP server through the OFFICIAL MCP Python client.

Works with the 1.x client (ClientSession + stdio_client) and the 2.x client
(Client, which first probes `server/discover`, then falls back to the
initialize handshake). Used by tests/test_mcp.py and the CI job.

usage: python mcp_client_check.py <python-with-roundtable> <RT_HOME> <seat>
prints: OK <protocol-version-or-mode> <n tools> and exits 0
"""

from __future__ import annotations

import asyncio
import sys


async def main(server_python: str, home: str, seat: str) -> int:
    import mcp

    version = getattr(mcp, "__version__", None)
    if version is None:
        from importlib.metadata import version as v

        version = v("mcp")
    major = int(version.split(".")[0])
    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(command=server_python, args=["-m", "roundtable_ai", "mcp"], env={"RT_HOME": home})
    if major >= 2:
        from mcp import Client

        async with Client(params, mode="auto") as client:
            tools = await client.list_tools()
            names = sorted(t.name for t in tools.tools)
            joined = await client.call_tool("rt_sync", {"join": seat})
            text = joined.content[0].text
            key = text.split('key="', 1)[1].split('"', 1)[0]
            listed = await client.call_tool("rt_task", {"action": "ready", "key": key})
            bad = await client.call_tool("rt_task", {"action": "claim", "task": "T99", "key": key})
    else:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                joined = await session.call_tool("rt_sync", {"join": seat})
                text = joined.content[0].text
                key = text.split('key="', 1)[1].split('"', 1)[0]
                listed = await session.call_tool("rt_task", {"action": "ready", "key": key})
                bad = await session.call_tool("rt_task", {"action": "claim", "task": "T99", "key": key})
    def err(r):
        return getattr(r, "is_error", None) if hasattr(r, "is_error") else r.isError

    assert len(names) == 8, names
    assert "ROUNDTABLE: you are seat" in text, text
    assert not err(listed), listed.content[0].text
    assert err(bad) and "no task T99" in bad.content[0].text, bad.content[0].text
    print(f"OK mcp-client {version} tools={len(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(*sys.argv[1:4])))
