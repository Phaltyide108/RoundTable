"""Roundtable: several AI models plan, build and review one project together.

Each model keeps its own chat in its own app (Claude Code, the Claude app,
ChatGPT's Codex mode, Codex CLI, ...). They never talk to each other directly:
every seat reads and writes one shared record through Roundtable's MCP server.
"""

__version__ = "0.2.0"
