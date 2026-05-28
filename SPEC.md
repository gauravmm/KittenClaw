# kittenclaw - spec (rough draft)

A minimal chat harness for teaching. The goal is **to help students run their
own tiny claws** - i.e., fork this repo in a Codespace, point it at a model
they like, edit `system.md.j2`, drop new files into `workspace/skills/`, watch behavior
change, and walk away understanding how agentic harnesses actually work.

That goal drives every design call below:

- A curious student should be able to **read the whole codebase in one
  sitting** and understand every line. No frameworks, no clever abstractions,
  no hidden state.
- Every interesting concept (the turn loop, tool dispatch, prompt
  construction, cache behavior) should sit in plain view, not behind a
  library boundary the student has to peel back.
- The harness should be **forkable, not extensible**. Students aren't writing
  plugins against a stable API; they're rewriting parts of `kittenclaw` to
  build their own version. Keep the surface area small enough that this is
  cheap, not scary.

## Goals

1. Talk to an **OpenAI-compatible chat completions API** (any provider that speaks
   `/v1/chat/completions` - OpenAI, OpenRouter, vLLM, llama.cpp server, etc.).
   Students should be able to swap providers by editing `kittenclaw.toml` or
   passing `--preset <name>` - no code changes.
2. Expose a small, **fixed tool surface**: web access (read-only) + file access
   (sandboxed to one local workspace directory). Few enough tools that a
   student can hold the whole capability set in their head.
3. Support **skills**: ordinary markdown files in `workspace/skills/` whose
   frontmatter is injected into the system prompt - so students can teach
   the bot new behaviors by adding files, no code change.
4. **Telegram** is the only user-facing channel. One Telegram chat = one
   kittenclaw conversation. Each student runs their own bot.
5. **Raw transparency**: every open conversation's exact wire-format message
   history lives in a single human-readable file on disk. `cat` and you see
   exactly what the model sees - there is no "internal" representation.
6. **Cache friendly, and observably so**: the prompt prefix must be stable,
   *and* the loop reports cache hit ratios to the log so students can watch
   the caching they designed for actually happen.

## Non-goals

- Multi-user auth, accounts, rate limits beyond what Telegram gives us.
- Streaming UX, fancy markdown rendering, image input/output.
- Tool sandboxing beyond "files stay in one directory."
- Persistence beyond flat files. No DB, no migrations.
- Production hardening. This is a teaching harness.

## Layout

```
kittenclaw/
  kittenclaw/
    __main__.py       # the harness: CLI + config + turn loop + model client +
                      #              prompt rendering + JSONL conversation I/O
    tools.py          # the 5 tools + JSON Schemas + dispatcher
    telegram_bot.py   # python-telegram-bot wiring (handlers, polling, disclaimer)
  workspace/          # the model's sandbox for file_read/file_write/file_list
    skills/           # ordinary *.md files - frontmatter injected into the prompt
  conversations/      # one file per open Telegram chat (see "Conversations")
  system.md.j2        # Jinja2-over-markdown system prompt template
  kittenclaw.toml     # model presets + non-secret config (see "Configuration")
  .env.example        # placeholder secrets, copied to .env by the student
  pyproject.toml      # uv-managed deps + console script
  uv.lock             # committed for reproducible installs
  README.md
```

Three files, each answering one question:

- `__main__.py` - **"how does the harness work end-to-end?"** Holds the
  whole runtime loop (read message → load JSONL → call model → dispatch
  tool calls → append → send reply), plus CLI parsing, `kittenclaw.toml`
  loading with `${VAR}` expansion, system-prompt rendering, and JSONL I/O.
  Expected size: ~300 lines including comments. Keeping these together
  means students can read the entire control flow without jumping files.
- `tools.py` - **"what can the model do?"** The five tools, their JSON
  Schemas, the path-safety helper, the dispatcher.
- `telegram_bot.py` - **"how does Telegram plug in?"** Handlers for
  messages and `/clear` / `/disclaimer`, the per-chat lock dict, the
  first-contact disclaimer, the empty-response fallback.

## The loop

For each Telegram message received:

1. Acquire the **per-chat lock** for this `chat_id` (a dict of `asyncio.Lock`
   keyed by chat - different chats run concurrently; the same chat is serial).
2. Look for an active `conversations/<chat_id>-*.jsonl` for this chat.
   - **None exists** (brand-new chat or first message after `/clear`): compute
     the next serial (`max(existing serials across active + archive) + 1`,
     or `001`), render the system prompt from `system.md.j2` + current
     skills, and write the new file with just the system message.
   - **A file exists**: read it line-by-line into the in-memory `messages`
     list via `jsonlines.open(path).iter(skip_invalid=True)`.
3. Append the user message (in memory; one JSONL line written to the file).
4. Call the model.
5. If the model returned tool calls: execute each, append the
   assistant-with-tool-calls message and each tool result (in memory; one
   JSONL line per message), goto 4.
6. If the model returned a final text reply: append it; send via Telegram
   (or the `(no content)` placeholder if the reply is empty); release the
   lock; done.

## Tools

Exactly five. All defined in `tools.py`. Schemas are the OpenAI
function-calling JSON Schema format and are passed to the model via
`chat.completions.create(tools=[...])` - *not* interpolated into the system
prompt. The system prompt describes when to use which tool in prose; the
schemas are the API's concern.

| Name          | Purpose                                                |
|---------------|--------------------------------------------------------|
| `web_fetch`   | GET a URL. Optional `as_text` flag strips HTML → plain text; otherwise returns the raw response body. |
| `web_search`  | Scrape DuckDuckGo's HTML endpoint → list of `{title, url, snippet}`. Zero config; **expected to break periodically** as DDG changes their HTML. When it does, fixing the selector is a great student exercise - first taste of "tools that touch the real world degrade." |
| `file_list`   | List entries under a workspace-relative path.          |
| `file_read`   | Read a workspace-relative file as text.                |
| `file_write`  | Write/overwrite a workspace-relative file.             |

Skills live at `workspace/skills/`, inside the sandbox. The model loads a
skill's body by calling `file_read("skills/<name>.md")` like any other file -
no dedicated `read_skill` tool. One fewer tool, no special-case path in the
dispatcher, and students see that "a skill is just a file the model reads."

Path safety: every workspace path is resolved with `Path.resolve()` and
checked to be under `workspace/` (real path, after symlink resolution).
**Hidden files and directories are also rejected** - any path component
starting with `.` (e.g. `.gitkeep`, `.env`, `.git/`) is off-limits to all
file tools, including `file_list` (which filters them from listings so the
model doesn't even see they exist). This protects repo plumbing
(`.gitkeep` files keeping empty dirs alive) from accidental model edits and
keeps the conceptual model clean: "the model sees ordinary files only." One
helper, used everywhere - including the skill loader, since skills live
inside workspace too.

`web_fetch` takes `url` (required) and `as_text` (optional, default `true`).
With `as_text=true`, the response body is passed through
`BeautifulSoup(html, "html.parser").get_text(" ", strip=True)` to collapse
into plain text. With `as_text=false`, the raw body comes back unmodified -
useful for JSON APIs, robots.txt, RSS, etc. No JavaScript execution.

No `file_delete`, no shell, no subprocess. Educational simplicity > capability.

**Tool errors.** If a tool raises (HTTP 404, path-safety violation, file not
found, parse error from BeautifulSoup), the dispatcher catches the exception
and returns the tool message content as `{"error": "<exception class>:
<message>"}` (serialized JSON string). The model gets the error as a normal
`tool` message and decides how to respond - usually by apologizing, asking
the user a clarifying question, or trying a different approach. No
exception propagates out of a single tool call; the turn keeps going.

## Skills and system prompt

A skill is a markdown file in `workspace/skills/` with a YAML **frontmatter**
block and a free-form body:

```markdown
---
name: web-research
description: Fetch and synthesize information from web sources, citing URLs.
---

# Long-form skill body

Step-by-step instructions, examples, edge cases - anything the model should
follow when this skill is active.
```

The filename (sans `.md`) is canonical; `name:` in frontmatter is optional
and must match the filename if present. Extra frontmatter keys flow through
into the template as-is.

**Only the frontmatter is injected into the system prompt** - the body is not.
The body is loaded on demand by the model calling
`file_read("skills/<name>.md")`. This keeps the system prompt small
(cache-warm) and turns skill discovery into a deliberate, observable step
that students can watch happen in the conversation JSONL.

`system.md.j2` is a **Jinja2-over-markdown** template, rendered **once when
a conversation is first created** and written as the first message in the
JSONL. Subsequent turns re-use the stored system message verbatim - they
never re-render. That means changes to `system.md.j2` or `workspace/skills/`
affect *new* conversations only; existing ones keep their original prompt.
This is by design: the prefix is literally the same bytes across every turn
of a conversation, by construction.

The template receives one variable: `skills`, a list of frontmatter dicts
(one per `workspace/skills/*.md` file), sorted by filename for stable
output.

A minimal default `system.md.j2`:

```jinja
You are a helpful assistant running inside kittenclaw, a teaching harness.

You have file access (scoped to `./workspace`) and web access. Prefer calling
tools over guessing; cite any URL you fetch; ask before overwriting files.

{% if skills %}
## Skills available

{% for skill in skills %}
- **{{ skill.name }}** - {{ skill.description }}
{% endfor %}

Call `file_read("skills/<name>.md")` to load a skill's full instructions
before applying it.
{% endif %}
```

Editing `system.md.j2` is part of the teaching surface - students change it,
start a new conversation, and watch the bot's behavior shift.

### Default skill: weather + memory pathway

One starter skill ships in `workspace/skills/weather.md`. It uses
[wttr.in](https://wttr.in/) (no API key) and introduces the **memory
pathway**.

The interesting bit: `wttr.in/` with no location geolocates the *caller's*
IP (i.e., the Codespace's datacenter) - wrong. And single-name cities pick
the most populous match (`wttr.in/springfield` → Illinois, USA). So the
skill asks the user for their **city and country** on first use, persists
the answer to `workspace/memory/location.md`, and reuses it forever after.

**Memory pathway**: kittenclaw has no special memory subsystem - just the
workspace filesystem reached via `file_read`/`file_write`/`file_list`. By
convention, skills write cross-conversation state to
`workspace/memory/<topic>.md` (plain markdown, free form). Students can
`cat workspace/memory/*.md` and read exactly what the bot remembers. The
memory is the file, and the file is the memory.

The weather skill's pattern:

1. `file_read("memory/location.md")`. On `FileNotFoundError`, ask the user
   for city + country, then `file_write` the answer (e.g., `Wellington, NZ`).
2. `web_fetch("https://wttr.in/<city>,<country>?format=4")` returns a one-line
   summary like `wellington,nz: ☀️ 🌡️+11°C 🌬️↖14km/h`. Plain text; default
   `as_text=true` is right. (`format=3` is simpler; `format=j1` is full JSON,
   noted as swap-in alternatives.)
3. Paraphrase to the user; cite the URL.

## Conversations

One file per *conversation*: `conversations/<chat_id>-<serial>.jsonl`, where
`<chat_id>` is the Telegram chat ID (a stable integer, always present) and
`<serial>` is a zero-padded three-digit counter (`001`, `002`, ...) that
increments each time `/clear` starts a fresh conversation in that chat.

So a chat that has been cleared twice has files like:

```
conversations/
  12345-003.jsonl             # active conversation
  archive/
    12345-001.jsonl
    12345-002.jsonl
```

The active file lives at the top level; archived ones move to `archive/` with
the **same filename** (so the serial number is durable). The next serial for a
chat is `max(existing serials across active + archive for this chat_id) + 1`,
or `001` for a brand-new chat.

Format: **JSON Lines** - one JSON object per line, each line a single chat
message in the exact wire shape sent to the model:

```jsonl
{"role": "system", "content": "You are a helpful assistant..."}
{"role": "user", "content": "hello"}
{"role": "assistant", "content": null, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "web_fetch", "arguments": "{\"url\": \"...\"}"}}]}
{"role": "tool", "tool_call_id": "call_1", "content": "..."}
{"role": "assistant", "content": "hi!"}
```

The whole file, read top-to-bottom and parsed line-by-line, **is** the
`messages` array sent on the wire. No extra wrapping, no separate "internal"
representation. `cat conversations/<chat_id>-<serial>.jsonl | jq -s` gives you
the array as the model sees it.

The "pretty-printed view" comes from a **VS Code extension** the devcontainer
auto-installs:
[`lehoanganh298.json-lines-viewer`](https://marketplace.visualstudio.com/items?itemName=lehoanganh298.json-lines-viewer)
(open source: <https://github.com/lehoanganh298/json-lines-viewer>) - opens
each line as a foldable, syntax-highlighted JSON block. The on-disk file
stays compact JSONL and append-only; the extension only changes the *view*.

Reads and writes go through the [`jsonlines`](https://pypi.org/project/jsonlines/)
library - a thin wrapper that handles the line-terminated JSON pattern and,
importantly, surfaces `skip_invalid=True` on read so corrupt lines are
skipped rather than crashing the loader.

**Lifecycle of a conversation file:**

- **First message in a new chat**: render `system.md.j2` with the *current*
  skill set; write the resulting system message as the first line via
  `jsonlines.open(path, mode="w").write(msg)`. The system prompt is only
  rendered this once for the conversation.
- **Every subsequent turn**: read the file with
  `jsonlines.open(path).iter(skip_invalid=True)` into the in-memory
  `messages` list; append new messages with `jsonlines.open(path, mode="a")`.
- **Atomicity**: each line is one complete JSON object terminated by `\n`.
  A crash mid-write leaves at most one partial trailing line - and
  `skip_invalid=True` ignores it on the next read.
- **Append-only by construction.** The code never mutates existing lines.

### Telegram behaviors

**First-contact disclaimer.** The first time a chat ID contacts the bot - i.e.
when there is no file matching `conversations/<chat_id>-*.jsonl` and no file
matching `conversations/archive/<chat_id>-*.jsonl` - the bot sends the
kittenclaw logo as a **sticker** (`send_sticker` with
`./kittenclaw.webp`), followed by the disclaimer text as a **separate
message** (`send_message`). Then it handles the user's message normally. No
greeted-users state file is needed; the filesystem itself answers "have I
met this chat before?"

The disclaimer text is an **inline constant** in `telegram_bot.py` - short
enough that an external file would be ceremony, and keeping it next to the
handler makes the teaching obvious. The sticker asset
(`./kittenclaw.webp`, 512×294, transparent background, ≤512 KB) is checked
into the repo; if the source `kittenclaw_orig.png` is updated, regenerate
via `cwebp -resize 512 0 -q 90 -alpha_q 100 -exact kittenclaw_orig.png -o
kittenclaw.webp` (also documented in the README). `-alpha_q 100 -exact`
keep the alpha channel lossless and preserve RGB in transparent areas.

**Empty-response fallback.** If a model turn completes (no more tool calls
pending) and the final assistant message has no text content - empty string,
`null`, or only whitespace - the bot sends a placeholder `(no content)`
message rather than going silent. The empty assistant message is still saved
to the conversation file so the wire history is faithful; the placeholder is
purely a Telegram-side affordance so the student knows the turn ended.

**Long-message handling.** Telegram's per-message limit is 4096 chars and
`python-telegram-bot` does not auto-split. The bot chunks any assistant
reply longer than 4000 chars (leaving headroom for markdown overhead) at
the last paragraph break before the boundary, sending the parts as
sequential `send_message` calls. The full untouched reply is still saved to
the JSONL - splitting is a Telegram-side affordance only.

**Commands.**

- `/clear` - archive the current conversation and start fresh. The active
  `conversations/<chat_id>-<serial>.jsonl` is moved into
  `conversations/archive/` with the **same filename** (the serial number is
  preserved). The next message from this chat will re-render `system.md.j2`
  against the *current* skill set and start a new file with serial+1. The
  bot acknowledges with a short confirmation. Note: archiving a conversation
  does **not** re-trigger the first-contact disclaimer - the archived file
  is still evidence that this chat has been greeted.
- `/disclaimer` - re-send the disclaimer (sticker + text message). Useful in
  classroom demos. Does *not* alter conversation state.

**Archive folder**: `conversations/archive/` holds every conversation that
has been ended via `/clear`. The harness never deletes a conversation -
moving to the archive folder *is* "completion." Students can grep across the
archive to review prior runs, which is half the educational point.

## Cache telemetry

The system prompt is persisted (not re-rendered) per conversation, skills load
on demand after the prefix, and tool results are deterministic - so the prefix
caches by construction. A comment block at the top of `__main__.py` calls
this out for students.

After every model call, the loop **reports the provider's cache stats to the
standard log stream**. This is one of the core things the harness is meant to
teach: prompt caching is real, observable, and worth designing around. It is
*not* exposed to Telegram - students read it in the terminal alongside the
rest of the harness's logs.

The model client parses the `usage` block of the response and emits a one-line
summary per turn:

```
[chat 12345] turn 4   prompt=2843 (cached=2611, 91.8%)  completion=72  total=2915
```

We only support the **OpenAI-style** `usage` shape:

- `prompt_tokens`, `completion_tokens`, `total_tokens` - always present.
- `prompt_tokens_details.cached_tokens` - present when the provider reports
  cache hits. Hit ratio = `cached_tokens / prompt_tokens`.

This shape is returned by OpenAI directly, by vLLM with `--enable-prefix-caching`,
and by OpenRouter when routing to OpenAI / DeepSeek / Gemini. Anthropic's
distinct `cache_read_input_tokens` / `cache_creation_input_tokens` fields are
**not** supported - students using Anthropic-via-OpenRouter will see `cached=?`,
and that's a deliberate teaching artifact rather than a feature to add.

**OpenRouter note**: it supports cache reporting, but you must send
`"usage": {"include": true}` in the request body - OpenRouter omits the
expanded usage block by default. With the openai SDK, this is passed via
`extra_body={"usage": {"include": True}}` on the `chat.completions.create`
call. The model client always includes it.

When `prompt_tokens_details.cached_tokens` is absent from the response, the
reporter logs `cached=?` rather than guessing. A `cached=0` line means the
provider reported the field but zero hits - informative on its own: the prefix
may be too short, this may be the first request, or the cache TTL (typically
5-10 minutes idle) may have expired.

## Configuration

Three channels, with a clear split:

- **`.env`** - secrets only. Loaded at startup via `python-dotenv`. Variables:
  - `OPENROUTER_API_KEY` - model API key for the default preset. Sign-up at
    [openrouter.ai](https://openrouter.ai) is free and gives access to a
    rotating set of free models.
  - `TELEGRAM_BOT_TOKEN` - the Telegram bot token.
  - Additional keys (`OPENAI_API_KEY`, etc.) only needed if the student
    selects a preset that references them.
- **`kittenclaw.toml`** - everything else non-secret. Ships in the repo with
  sensible defaults. Students edit this file to add new model presets,
  change the active preset, or tweak the context budget.
- **CLI flags** - minimal, just to switch between configured presets at
  invocation time without editing the file.

### `kittenclaw.toml`

```toml
# Which preset to use if --preset isn't passed on the CLI.
default_preset = "openrouter-free"

# Default. Uses OpenRouter's catch-all `openrouter/free` router, which
# picks a free model at random *and filters for tool-calling support* per
# request. Students need only an OpenRouter API key (free to obtain at
# openrouter.ai) - no model pinning, no rotation maintenance.
[models.openrouter-free]
base_url = "https://openrouter.ai/api/v1"
model = "openrouter/free"
max_context_tokens = 200000
max_response_tokens = 4096
api_key = "${OPENROUTER_API_KEY}"

[models.openai-mini]
base_url = "https://api.openai.com/v1"
model = "gpt-4.1-mini"
max_context_tokens = 128000
max_response_tokens = 4096
api_key = "${OPENAI_API_KEY}"

[models.openrouter-sonnet]
base_url = "https://openrouter.ai/api/v1"
model = "anthropic/claude-sonnet-4.5"
max_context_tokens = 200000
max_response_tokens = 8192
api_key = "${OPENROUTER_API_KEY}"

[models.local-vllm]
base_url = "http://localhost:8000/v1"
model = "Qwen/Qwen2.5-7B-Instruct"
max_context_tokens = 32000
max_response_tokens = 2048
api_key = "not-needed"
```

**`${VAR}` env interpolation.** Any string value in the TOML can reference an
environment variable via `${VAR}`. Substitution happens after `tomllib.load()`
by walking the parsed dict; ~10 lines of code. Unset variables raise a clear
error at startup (`kittenclaw.toml references ${FOO} but it's not set in
.env`) - fail fast, no silent fallbacks. This keeps secrets in `.env` while
the structural config lives in the TOML.

The path is **hardcoded to `./kittenclaw.toml`** at the repo root - see
"Hardcoded paths" below.

### CLI surface

```text
kittenclaw [--preset <name>] [--verbose]
```

That's it. Two flags:

- `--preset <name>` - pick a model preset by name from `kittenclaw.toml`.
  Defaults to `default_preset` from the same file.
- `--verbose` - emit per-tool-call and per-turn debug logging on top of the
  default cache-telemetry line.

Everything else - `base_url`, `model`, `max_context_tokens`,
`max_response_tokens`, `api_key` - comes from the selected preset.

### Hardcoded paths

Repo-root paths, baked into the source. No flags, no settings:

| Path                       | What                                  |
|----------------------------|---------------------------------------|
| `./kittenclaw.toml`        | this config file                      |
| `./system.md.j2`           | system prompt template                |
| `./workspace/`             | model's file sandbox                  |
| `./workspace/skills/`      | skill files                           |
| `./workspace/memory/`      | conventional location for memory      |
| `./conversations/`         | active conversation JSONLs            |
| `./conversations/archive/` | archived conversations after `/clear` |
| `./kittenclaw.webp`   | sticker sent on first contact         |
| `./kittenclaw_orig.png`    | source for the sticker conversion     |

Rationale: forking the repo *is* the customization story - students teach by
editing files, not by stringing flags. One fewer knob to explain at every
site.

### `max_context_tokens` and `max_response_tokens`

`max_response_tokens` is passed to the model on every call (as `max_tokens`
on the openai SDK's `chat.completions.create`), capping how much the model
can generate in one turn. Recent OpenAI o-series models reject `max_tokens`
in favor of `max_completion_tokens`; the SDK ≥1.40 auto-routes between the
two. If a student hits a rejection on an older SDK or via a strict proxy,
the fix is to send `max_completion_tokens` instead - one parameter name to
swap, noted in a code comment.

`max_context_tokens` is enforced as an **auto-clear threshold** after each
model turn. The check is:

```
prompt_tokens (from response.usage) + max_response_tokens >= max_context_tokens
```

This asks: "could the *next* turn fit a full response?" If not, the current
conversation is auto-archived (same mechanism as `/clear` - moved to
`conversations/archive/<chat_id>-<serial>.jsonl`) and the bot sends a single
Telegram message:

> ⚠️ **Max context reached.** This conversation has been auto-cleared. Your
> next message will start a fresh one.

The next user message starts a new conversation file with serial+1 and
re-renders `system.md.j2` against the current skill set. No tokenizer
dependency (`tiktoken` etc.) - we only use numbers the provider already
reported via `response.usage`. No automatic truncation - truncating
in-conversation would break the cache and confuse students about what the
model saw; clearing is honest about the state change.

The same one-line log entry as before is still emitted on every turn
(prompt/cached/completion/total). When the auto-clear fires, an additional
log line marks it:

```
[chat 12345] auto-clear: prompt=125904 + max_response=4096 >= max_context=128000.
```

### `.env.example`

Ships in the repo with placeholder values and a comment pointing to where
each token is obtained. The student copies it to `.env` and fills in the
lines for the providers they want to use. Only the API keys for presets the
student actually selects need to be populated - `${VAR}` interpolation only
runs on the selected preset.

## Implementation language and packaging

- **Language**: **Python 3.14** (the current latest stable, released October
  2025). Pinned via `.python-version` and `requires-python = ">=3.14"` in
  `pyproject.toml`. uv reads `.python-version` and installs the matching
  interpreter automatically if it's not already present, so every student's
  Codespace ends up on the same version with zero ceremony.
- **Package manager**: [**uv**](https://github.com/astral-sh/uv). Dependencies
  declared in `pyproject.toml`; `uv.lock` committed for reproducible
  installs. The Codespace devcontainer uses `uv sync` on create (see below).
  uv is fast enough that "rebuild Codespace, start bot" stays under a minute,
  which matters when each student has 30 minutes to play.
- **Model client**: the official [`openai`](https://github.com/openai/openai-python)
  Python SDK, used in its **OpenAI-compatible** mode - i.e.
  `AsyncOpenAI(base_url=..., api_key=...)`. Works against OpenAI, OpenRouter,
  vLLM, llama.cpp's server, and anything else that speaks
  `/v1/chat/completions`. We use the same library every other Python project
  uses to talk to these endpoints - students leave with transferable muscle
  memory rather than a bespoke client to forget. The wire shape is still
  fully visible: tool schemas, messages list, and the `usage` block all come
  through as typed objects whose JSON shape exactly mirrors the API docs.
- **Concurrency model**: single-process **asyncio**, no threads. The whole
  app runs on `python-telegram-bot`'s event loop:
  - PTB delivers each Telegram message as a coroutine.
  - The turn loop is `async def`, awaiting the model (`AsyncOpenAI`) and
    `web_fetch` / `web_search` (async `httpx`).
  - Per-chat isolation is an `asyncio.Lock` keyed by `chat_id` - different
    chats interleave on the loop, the same chat is serial.
  - File tools (`file_read`/`file_write`/`file_list`) are synchronous -
    workspace files are local and tiny, so wrapping them in `asyncio.to_thread`
    would be more ceremony than the I/O saves. Acknowledged as a teaching
    artifact ("if a tool actually blocked the loop, you'd notice"); the
    blocking is intentional and observable.

  There are no background tasks, no thread pool, no `multiprocessing`. One
  event loop, one process, one Telegram poll, many concurrent chats.

### Dependencies

- `openai` - model client, used in OpenAI-compatible mode (see above). The
  SDK uses `httpx` under the hood and exposes `response.usage` as a Pydantic
  object that we read directly for cache telemetry.
- `python-telegram-bot` - Telegram client. Idiomatic handlers, long-polling.
  Worth the dep; rolling it by hand obscures more than it teaches. Note: PTB
  does *not* auto-split long messages - see "Long-message handling" below.
- `httpx` - used directly for `web_fetch` and `web_search` (the openai SDK
  brings it as a transitive dep anyway). Async, to play nicely with
  `python-telegram-bot`'s asyncio loop and per-chat concurrency.
- `python-dotenv` - load `.env`.
- `jinja2` - render the system-prompt template.
- `jsonlines` - read/write JSONL conversation files with `skip_invalid` for
  resilience against partial trailing lines from crashes.
- `pyyaml` - parse skill frontmatter.
- `beautifulsoup4` - HTML → text for `web_fetch(as_text=true)` and for the
  DuckDuckGo HTML scrape in `web_search`.

## Deployment: GitHub Codespaces

The primary deployment vehicle is **GitHub Codespaces**. Each student forks the
repo, opens a Codespace, fills in `.env`, and runs the bot. This shapes a few
design choices:

- **Long polling, not webhooks.** Telegram long polling makes only *outbound*
  connections, so it works from a Codespace with no port forwarding, no public
  URL, no ngrok. `python-telegram-bot`'s default `Application.run_polling()`
  fits exactly.
- **Devcontainer.** Ship `.devcontainer/devcontainer.json` that:
  - Uses a Python 3.14 base image (matching the project's `.python-version`).
    uv can also bootstrap the interpreter itself, so the base image's Python
    version is mostly a starting point - if it differs, `uv sync` corrects it.
  - Installs `uv` via the `ghcr.io/astral-sh/uv` devcontainer feature (or
    `curl -LsSf https://astral.sh/uv/install.sh | sh` in `postCreateCommand`).
  - Runs `uv sync` on create to install dependencies into a project-local
    `.venv/`. The bot is then launched with `uv run python -m kittenclaw`.
  - Auto-copies `.env.example` → `.env` on first open via `postCreateCommand`,
    so the student sees an editable file in the explorer.
  - Sets `"customizations.vscode.extensions"` to install:
    - `ms-python.python` - Python language support.
    - `lehoanganh298.json-lines-viewer` - pretty-prints each line of
      `conversations/*.jsonl` as a foldable JSON block. This is how students
      read the wire history.
    - A markdown linter of your choice (e.g. `DavidAnson.vscode-markdownlint`).

    The editor experience matters when each student has 30 minutes to play.
- **Per-student bot tokens.** Each student creates their own bot via
  `@BotFather`; `.env` is gitignored. No shared infrastructure.
- **Ephemeral filesystem is fine.** Conversations and workspace files live in
  the Codespace; if the Codespace is rebuilt, they're gone. That's the right
  tradeoff for a teaching tool - clean slate per session is a feature.
- **No background daemon.** The bot runs in the foreground of the Codespace
  terminal (`uv run python -m kittenclaw`). Students see logs, Ctrl-C to
  stop. Ship `.vscode/launch.json` with a "Run kittenclaw" configuration so
  F5 starts the bot in the debugger - students can drop breakpoints into
  the turn loop and step through.

The README's quickstart should be: *Fork → Open in Codespace → Edit `.env` →
`uv run python -m kittenclaw` → DM your bot on Telegram.* Five steps, none
of them require leaving the browser.
