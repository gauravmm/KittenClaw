# <img src="kittenclaw.webp" alt="" height="40" valign="middle"> kittenclaw

A minimal chat harness for teaching agentic loops. Fork it, point it at a
model you like, edit `system.md.j2`, drop new files into `workspace/skills/`,
watch the bot change. Read the [spec](SPEC.md) for the full design rationale.

The whole runtime is three Python files:

| File                              | Answers                                    |
| --------------------------------- | ------------------------------------------ |
| `kittenclaw/__main__.py`          | how does the harness work end-to-end?      |
| `kittenclaw/tools.py`             | what can the model do?                     |
| `kittenclaw/telegram_bot.py`      | how does Telegram plug in?                 |

## Quickstart (Codespaces)

1. **Fork** this repo on GitHub.
2. **Open in Codespace** - the devcontainer installs Python 3.14 + uv,
   runs `uv sync`, and copies `.env.example` → `.env`.
3. **Get a Telegram bot token** from [@BotFather](https://t.me/BotFather) on
   Telegram. Paste it into `.env` as `TELEGRAM_BOT_TOKEN=...`.
4. **Get an OpenRouter API key** (free) at
   [openrouter.ai](https://openrouter.ai). Paste it as `OPENROUTER_API_KEY=...`.
5. **Run** the bot:

   ```bash
   uv run python -m kittenclaw
   ```

   Then DM your bot on Telegram. The first message gets the kittenclaw logo
   + a disclaimer; subsequent messages run through the model.

That's it. No port forwarding, no public URL - long polling makes only
outbound connections, so Codespaces is fine.

## Local install

If you'd rather run on your own machine:

```bash
uv sync
cp .env.example .env  # fill in TELEGRAM_BOT_TOKEN + OPENROUTER_API_KEY
uv run python -m kittenclaw
```

You'll need [`uv`](https://github.com/astral-sh/uv) installed. uv picks up
`.python-version` and bootstraps Python 3.14 if you don't have it.

## CLI

```text
kittenclaw [--preset <name>] [--verbose] [--once "MESSAGE"]
```

- `--preset <name>` - pick a preset from `kittenclaw.toml`. Defaults to
  `default_preset` (currently `cerebras`).
- `--verbose` - emit per-tool-call debug logging on top of the default
  one-line-per-turn token summary.
- `--once "MESSAGE"` - process a single message locally and exit, with no
  Telegram token and no polling. The turn runs through the same `turn_loop`
  the bot uses and the reply is printed to stdout. Repeated calls reuse one
  debug conversation (`conversations/0-*.jsonl`), so you can hold a
  multi-turn exchange one message at a time; delete that file to start over.
  Handy for trying the bot without a Telegram setup, or for debugging.

Everything else (`base_url`, `model`, token budgets, API key) comes from
the selected preset.

### What you'll see in the logs

After every model call, one line with the provider's reported token counts:

```
[chat 12345] turn 4  prompt=2843  completion=72  total=2915
```

`prompt` is what feeds the auto-clear check (when the next turn would no
longer fit `max_context_tokens`, the conversation is archived). The harness
keeps the prompt prefix cache-friendly by construction, but measuring cache
hit rates is taught separately and not reported here.

## Files & directories

| Path                       | What                                           |
| -------------------------- | ---------------------------------------------- |
| `kittenclaw.toml`          | model presets (edit to add/select)             |
| `system.md.j2`             | Jinja2 system-prompt template                  |
| `workspace/`               | the model's sandbox (`file_*` tools live here) |
| `workspace/skills/*.md`    | skills - frontmatter is injected into prompt   |
| `workspace/memory/*.md`    | conventional cross-conversation memory         |
| `conversations/*.jsonl`    | active conversations (one per Telegram chat)   |
| `conversations/archive/`   | archived conversations after `/clear`          |

## Commands

- `/clear` - archive the current conversation; the next message starts
  fresh with a re-rendered system prompt.
- `/disclaimer` - re-show the welcome message.

## Reading conversation files

Conversations are JSON Lines: one wire-format message per line, exactly as
sent to the model. To see them as the model sees them:

```bash
cat conversations/<chat_id>-<serial>.jsonl | jq -s
```

## Teaching with kittenclaw

Things students can do without touching code:

- Edit `system.md.j2`, send a message, watch the behavior shift.
- Add a file to `workspace/skills/` (with frontmatter); start a new
  conversation (`/clear` first); see the model discover and read it.
- Add a model preset to `kittenclaw.toml`; rerun with `--preset <name>`.
- `cat` a `.jsonl` to see the exact wire history; trace why the model did
  what it did.
- Watch the cache-hit ratio in the terminal log.

Things that need code (and are kept short on purpose):

- A new tool - add a function + schema to `kittenclaw/tools.py`, wire it
  into `_HANDLERS`.
- A new command - add a `CommandHandler` in `kittenclaw/telegram_bot.py`.

## License

MIT. Have fun.
