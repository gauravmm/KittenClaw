---
name: weather
description: Look up current weather for the user's city via wttr.in, remembering location across conversations.
---

# Weather skill

Give the user a short, friendly weather report for their location.

## Memory pathway

Cross-conversation state lives in `workspace/memory/<topic>.md`. This skill
uses `workspace/memory/location.md`.

1. Try `file_read("memory/location.md")`.
2. On `FileNotFoundError`, ask the user for their **city and country** (e.g.
   "Wellington, NZ"). `wttr.in` with no location geolocates the *caller's*
   IP (the Codespace's datacenter), which is wrong; single-name cities also
   pick the most populous match, so country matters.
3. Once the user answers, `file_write("memory/location.md", "<city>, <country>")`.

## Fetching the weather

Call `web_fetch("https://wttr.in/<city>,<country>?format=4")` - returns a
single-line summary like `wellington,nz: ☀️ 🌡️+11°C 🌬️↖14km/h`. Plain text,
so the default `as_text=true` is fine.

Alternatives if you need a different shape:

- `format=3` - even shorter, just the city + temperature.
- `format=j1` - full JSON with hourly forecasts.

## Replying

Paraphrase the result conversationally and cite the wttr.in URL you used.
