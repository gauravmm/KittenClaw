"""The five tools the model can call: web_fetch, web_search, file_list,
file_read, file_write. Their JSON Schemas (passed to the model via the
`tools=` parameter), and a single dispatcher that maps a tool name + args to
its Python implementation.

The dispatcher catches *all* exceptions from tool calls and returns them as
`{"error": "<ExceptionClass>: <message>"}`. The model gets the error as a
normal `tool` message and decides how to respond — no exception ever
propagates out of a single tool call, so the turn loop stays alive.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

# Workspace root — every file tool resolves paths relative to this directory
# and refuses paths that escape it. Resolved once at import so symlink games
# can't shift the boundary at call time.
WORKSPACE = (Path(__file__).resolve().parent.parent / "workspace").resolve()


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def _safe_path(relpath: str) -> Path:
    """Resolve `relpath` under `WORKSPACE` and reject anything that escapes
    or touches a dotfile/dotdir. Used by every file tool *and* the skill
    loader — one helper, one rule.

    Hidden entries (any component starting with `.`) are off-limits: this
    protects repo plumbing like `.gitkeep` and keeps the model's mental
    model clean ("the model sees ordinary files only").
    """
    p = (WORKSPACE / relpath).resolve()
    # `is_relative_to` was added in 3.9; we're on 3.14.
    if not p.is_relative_to(WORKSPACE):
        raise ValueError(f"path escapes workspace: {relpath!r}")
    # Check every component *under* WORKSPACE — not the workspace dir itself.
    rel = p.relative_to(WORKSPACE)
    for part in rel.parts:
        if part.startswith("."):
            raise ValueError(f"hidden paths are not allowed: {relpath!r}")
    return p


# ---------------------------------------------------------------------------
# Web tools (async — they do real network I/O on the event loop)
# ---------------------------------------------------------------------------


async def web_fetch(url: str, as_text: bool = True) -> str:
    """GET a URL. With `as_text=true` (default), strip HTML to plain text;
    otherwise return the raw response body. No JS execution, ever."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        resp = await client.get(url, headers={"User-Agent": "kittenclaw/0.1"})
        resp.raise_for_status()
        body = resp.text
    if as_text:
        return BeautifulSoup(body, "html.parser").get_text(" ", strip=True)
    return body


async def web_search(query: str) -> list[dict]:
    """Scrape DuckDuckGo's HTML endpoint for `query`. Returns a list of
    {title, url, snippet}. Expected to break periodically as DDG changes
    their markup — fixing the selector is a great student exercise."""
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        # DDG's HTML endpoint rejects requests without a browser-y UA.
        resp = await client.post(
            url, headers={"User-Agent": "Mozilla/5.0 (kittenclaw)"}
        )
        resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for r in soup.select("div.result")[:10]:
        a = r.select_one("a.result__a")
        snip = r.select_one("a.result__snippet")
        if not a:
            continue
        results.append(
            {
                "title": a.get_text(" ", strip=True),
                "url": a.get("href", ""),
                "snippet": snip.get_text(" ", strip=True) if snip else "",
            }
        )
    return results


# ---------------------------------------------------------------------------
# File tools (sync — workspace files are local and tiny; see SPEC.md on why
# we don't wrap them in asyncio.to_thread)
# ---------------------------------------------------------------------------


def file_list(path: str = "") -> list[str]:
    """List entries under a workspace-relative directory. Hidden entries
    (starting with `.`) are filtered out so the model doesn't even see them."""
    d = _safe_path(path) if path else WORKSPACE
    if not d.is_dir():
        raise NotADirectoryError(f"{path!r} is not a directory")
    # Mark directories with a trailing slash — saves the model a round-trip.
    out = []
    for entry in sorted(d.iterdir()):
        if entry.name.startswith("."):
            continue
        out.append(entry.name + "/" if entry.is_dir() else entry.name)
    return out


def file_read(path: str) -> str:
    """Read a workspace-relative file as UTF-8 text."""
    return _safe_path(path).read_text(encoding="utf-8")


def file_write(path: str, content: str) -> str:
    """Write/overwrite a workspace-relative file. Creates parent dirs as
    needed so skills can `file_write("memory/foo.md", ...)` without ceremony.
    Returns a short confirmation string."""
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {path}"


# ---------------------------------------------------------------------------
# JSON Schemas — passed to the model via chat.completions.create(tools=[...]).
# These are *not* interpolated into the system prompt; the system prompt
# describes when to use each tool in prose.
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "GET a URL. Returns the response body. With as_text=true (default), HTML is stripped to plain text via BeautifulSoup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch."},
                    "as_text": {
                        "type": "boolean",
                        "description": "If true (default), strip HTML to plain text. If false, return the raw body — useful for JSON APIs, RSS, robots.txt, etc.",
                        "default": True,
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web via DuckDuckGo. Returns up to 10 results, each with title, url, and snippet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_list",
            "description": "List entries under a workspace-relative directory. Empty path lists the workspace root. Directories end with '/'. Hidden entries are filtered.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative directory path. Empty for root.",
                        "default": "",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read a workspace-relative file as text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write/overwrite a workspace-relative file. Parent directories are created as needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path.",
                    },
                    "content": {
                        "type": "string",
                        "description": "File contents (UTF-8 text).",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

# Map tool name → (callable, is_async). Sync vs async is the only branching
# the dispatcher needs to do.
_HANDLERS = {
    "web_fetch": (web_fetch, True),
    "web_search": (web_search, True),
    "file_list": (file_list, False),
    "file_read": (file_read, False),
    "file_write": (file_write, False),
}


async def dispatch(name: str, arguments_json: str) -> str:
    """Run a single tool call. Returns the string `content` the model will
    receive in its `tool` message. Any exception is caught and serialized as
    `{"error": "..."}` so the turn loop keeps going."""
    try:
        args = json.loads(arguments_json) if arguments_json else {}
        if name not in _HANDLERS:
            raise ValueError(f"unknown tool: {name}")
        fn, is_async = _HANDLERS[name]
        result = await fn(**args) if is_async else fn(**args)
        # The model expects a string; JSON-encode non-strings.
        return result if isinstance(result, str) else json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
