"""The apps a model can sit at the table from, described once for the CLI and the dashboard."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class App:
    key: str
    label: str              # what people call it
    company: str | None     # model maker it implies, if any
    start: str              # terminal | vscode | desktop | manual: how a chat for this seat is opened
    coding: bool            # can edit project files (gets its own working copy)
    binary: str | None = None   # command-line program `rt launch` runs
    connect: str | None = None  # `rt setup <x>` that connects this app, if it needs one
    folder: str | None = None   # per-seat settings file Roundtable writes in the seat's working copy (pins the seat)
    install: str | None = None  # how to install it, when missing


APPS: dict[str, App] = {a.key: a for a in (
    App("claude-code", "Claude Code in a terminal", "anthropic", "terminal", True, "claude",
        install="curl -fsSL https://claude.ai/install.sh | bash"),
    App("claude-vscode", "Claude Code in VS Code", "anthropic", "vscode", True, folder=".mcp.json"),
    App("claude-app", "Claude desktop app (plans and reviews only)", "anthropic", "desktop", False, connect="claude-app"),
    App("codex-cli", "Codex in a terminal", "openai", "terminal", True, "codex", install="npm install -g @openai/codex"),
    App("codex-vscode", "Codex in VS Code", "openai", "vscode", True, connect="codex"),
    App("codex-app", "ChatGPT desktop app (Codex mode)", "openai", "desktop", True, connect="codex"),
    App("gemini-cli", "Gemini CLI in a terminal", "google", "terminal", True, "gemini", folder=".gemini/settings.json",
        install="npm install -g @google/gemini-cli"),
    App("qwen-code", "Qwen Code in a terminal", "alibaba", "terminal", True, "qwen", folder=".qwen/settings.json",
        install="npm install -g @qwen-code/qwen-code"),
    App("opencode", "opencode in a terminal", None, "terminal", True, "opencode", folder="opencode.json",
        install="npm install -g opencode-ai"),
    App("copilot-cli", "GitHub Copilot CLI in a terminal", None, "terminal", True, "copilot", connect="copilot",
        install="npm install -g @github/copilot"),
    App("cursor", "Cursor editor", None, "editor", True, folder=".cursor/mcp.json"),
    App("other", "Another app that supports MCP", None, "manual", True),
)}

# Apps `rt launch` starts with Roundtable's own prompt and model flags (verified);
# other terminal apps are started plainly in the seat's folder.
FLAGGED = ("claude-code", "codex-cli")

# How hard each app can make its model think, as Roundtable passes it on start
# (claude --effort ...; codex -c model_reasoning_effort=...). Other apps: set it in the app.
EFFORTS: dict[str, tuple[str, ...]] = {
    "claude-code": ("low", "medium", "high", "xhigh", "max"),
    "codex-cli": ("minimal", "low", "medium", "high", "xhigh", "max", "ultra"),   # max/ultra: GPT-6.1 Sol and newer
    "opencode": ("minimal", "low", "medium", "high", "xhigh", "max"),   # opencode --variant (what the model offers)
}

COMPANIES = ("anthropic", "openai", "google", "alibaba", "xai", "meta", "mistral", "deepseek", "zhipu", "moonshot",
             "minimax", "xiaomi", "nvidia", "other")

# Model name fragments -> maker, for any app (opencode names them provider/model, e.g. opencode/glm-5.3).
MAKERS = (
    (("claude", "opus", "sonnet", "haiku", "fable", "mythos"), "anthropic"),
    (("gpt", "o1-", "o3", "o4-", "codex", "chatgpt"), "openai"),
    (("gemini", "gemma"), "google"),
    (("qwen", "qwq"), "alibaba"),
    (("grok",), "xai"),
    (("deepseek",), "deepseek"),
    (("glm", "zhipu", "z-ai"), "zhipu"),
    (("kimi", "moonshot"), "moonshot"),
    (("minimax",), "minimax"),
    (("mimo", "xiaomi"), "xiaomi"),
    (("nemotron", "nvidia"), "nvidia"),
    (("mistral", "codestral", "devstral", "magistral"), "mistral"),
    (("llama", "meta-"), "meta"),
)


def company_of_model(model: str) -> str | None:
    """Who makes a model, from its name: claude-opus-5-5, gpt-6.1-sol, opencode/glm-5.3, openrouter/qwen/qwen3.8-max ..."""
    m = (model or "").lower()
    parts = [p for p in m.replace(":", "/").split("/") if p]
    for name in reversed(parts or [m]):
        for frags, company in MAKERS:
            if any(name.startswith(f) or f"-{f}" in name for f in frags):
                return company
    for frags, company in MAKERS:              # a provider prefix alone: anthropic/..., openai/..., google/...
        if parts and parts[0] in (company, *frags):
            return company
    return None

# Model names known to work, offered as suggestions (people can type any name their app accepts).
MODEL_SUGGESTIONS = {
    "anthropic": ["claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5-5", "claude-haiku-5-5"],
    "openai": ["gpt-6.1-sol"],
    "google": [],
    "alibaba": [],
}


def get(key: str) -> App:
    return APPS.get(key) or APPS["other"]


def label(key: str) -> str:
    return get(key).label
