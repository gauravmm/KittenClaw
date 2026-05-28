# CLAUDE.md

Guidance for Claude Code (and other LLM coding assistants) working in this
repository. Humans should read [SPEC.md](SPEC.md) and [README.md](README.md)
first - this file assumes you've read both.

## What this project is

A **teaching harness**. The audience is students reading the code in one
sitting to learn how agentic chat loops work. Optimizing for readability,
brevity, and a small surface area is not a stylistic preference here - it
is the primary requirement.

## Code style rules

- **Three runtime files only**: `kittenclaw/__main__.py`, `tools.py`,
  `telegram_bot.py`. Do not split things out into more modules. If a helper
  is short, inline it.
- **No framework abstractions.** The whole point is that students see the
  control flow. Do not introduce dependency injection, plugin registries,
  base classes, decorators, etc. Plain functions and a dict of handlers is
  the ceiling.
- **No tokenizer dependencies.** Cache and budget accounting reads
  `response.usage` only.
- **Prefer editing existing files.** Do not create new `.py` files unless
  the spec demands it.
- **Comments should explain *why*.** Don't paraphrase the code. Especially
  worth commenting: cache-friendliness decisions, path-safety invariants,
  and anywhere the spec explicitly says "do it this way".
- **Hyphens only - no en-dashes or em-dashes.** Use the plain ASCII hyphen
  (`-`) everywhere: prose, comments, docstrings, user-facing strings. Do not
  use `U+2013` (en-dash) or `U+2014` (em-dash). This applies to all files in
  the repo, not just code.

## Things that are load-bearing - do not "clean up"

- **The system prompt is rendered once, when the conversation file is
  created.** It is *not* re-rendered on subsequent turns. This is what
  makes prefix caching work. If you find yourself adding a `render_system()`
  call inside `turn_loop`, stop.
- **Skills inject only their frontmatter into the system prompt.** The body
  is loaded by the model calling `file_read("skills/<name>.md")`. Do not
  inline the body into the prompt - it would blow up the prefix and
  invalidate the cache.
- **`extra_body={"usage": {"include": True}}`** on every model call. This
  is what makes OpenRouter expand the usage block so cache telemetry works
  there. Removing it silently kills the `cached=` numbers.
- **Path safety is via `_safe_path` in `tools.py`.** Both the workspace-
  containment check *and* the dotfile filter. Used in every file tool *and*
  the skill loader. Do not write a second version.
- **Per-chat locking is `asyncio.Lock` keyed by `chat_id`** in
  `app.bot_data["locks"]` (a `defaultdict`). Different chats interleave on
  the event loop; the same chat is serial. Do not introduce thread pools
  or process pools.
- **The conversation file *is* the messages list.** No separate in-memory
  schema, no parallel "internal" representation. Read with
  `jsonlines.open(...).iter(skip_invalid=True)`; append one line at a time.
- **`/clear` moves the active conversation file to
  `conversations/archive/` with the same filename.** The next user message
  creates a new file with serial+1. Do not delete archived files.
- **First-contact detection uses the filesystem.** `has_ever_greeted()`
  scans both `conversations/` and `conversations/archive/` for any file
  matching this chat_id. Do not add a separate `greeted.json`.

## Spec is authoritative

If something in the code seems wrong, check `SPEC.md` first - most of the
non-obvious choices are explained there with a teaching motivation. If
spec and code disagree, ask the user which is right before "fixing" either.

## Don't add

- Streaming UX, image input/output, fancy markdown rendering.
- Database, ORM, migrations.
- A web UI, a REST API, webhooks for Telegram.
- Tool sandboxing beyond "files stay under `workspace/`".
- A plugin system, an extension API, configurable tool registration.
- Multi-user auth, accounts, rate limits.
- Retry/backoff wrappers around the model call. The provider's SDK already
  retries; layering more obscures failure modes the student should see.
- A `file_delete` tool, a shell tool, a subprocess tool.

If a feature feels like it would make `kittenclaw` "more production-ready",
that's the signal it does *not* belong here.

## Permissions / running things

- `uv run python -m kittenclaw` launches the bot. Don't run this yourself
  unattended - it requires a Telegram bot token and will start polling.
- `uv sync` is safe to run.
- Conversation files under `conversations/*.jsonl` are runtime artifacts.
  Do not commit them; the `.gitignore` already excludes them.

## When asked to add a skill

1. Create `workspace/skills/<name>.md` with YAML frontmatter (`name`,
   `description`) and a markdown body of instructions.
2. The filename (sans `.md`) is canonical; `name:` in frontmatter must
   match if present.
3. *Do not* edit the system prompt template to mention the skill - the
   frontmatter loop in `system.md.j2` already lists it.
4. Existing conversations will not see the new skill until they `/clear`.
   This is intentional; mention it to the user if relevant.

## When asked to add a tool

1. Add a function (sync or async) to `kittenclaw/tools.py`.
2. Add a JSON Schema entry to `TOOL_SCHEMAS`.
3. Add a row to `_HANDLERS`: `"name": (fn, is_async)`.
4. Update `system.md.j2` if the tool needs prose guidance, *not* the schema.
5. That's it. No registration call elsewhere.

## When asked to add a model preset

Edit `kittenclaw.toml`. `${VAR}` references in string values are
interpolated from the environment at startup; unset vars fail loudly.
