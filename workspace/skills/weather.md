---
name: weather
description: Look up the current weather for a city.
---

# Weather skill

1. Get the location. Try `file_read("memory/location.md")`. On
   `FileNotFoundError`, ask the user for their **city and country** (e.g.
   "Wellington, NZ") - country matters, since `wttr.in` resolves a bare
   city to the most populous match - then
   `file_write("memory/location.md", "<city>, <country>")`.
2. Fetch it. `web_fetch("https://wttr.in/<city>,<country>?format=4")`
   returns one plain-text line: `wellington,nz: ☀️ 🌡️+11°C 🌬️↖14km/h`.
3. Reply. Restate that line in plain words and cite the URL. Give the wind
   as just its speed (e.g. "4 km/h") - ignore the direction arrow - and
   don't embellish the condition.
