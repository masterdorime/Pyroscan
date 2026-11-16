# Provider fixtures

Two different jobs live here. Do not mix them up.

## `<adapter>/live.*` — recorded provider responses

One real response per adapter, captured once and committed. These drive the
parser tests and are the **authoritative field list**: if a field name in the
spec disagrees with the capture, the capture wins.

| File | Source | Captured |
|---|---|---|
| `open_meteo/live.json` | Open-Meteo `v1/forecast` | — |
| `bmkg/live.json` | BMKG `publik/prakiraan-cuaca` | — |
| `firms/live.csv` | NASA FIRMS area CSV (VIIRS NRT) | — |

Fill the "Captured" column when you record one. If a capture could not be made
(no key, no network), say so here and mark the file **synthetic** rather than
leaving the reader to guess.

## `<key>/fallback.json` — the offline safety net

Used only when a key has no usable cache and every adapter failed. Served as
`status: error`, `reason: fixture_fallback`, `simulated: true`, and **never**
written to the cache. It keeps the console drawing instead of blank.

## Rules

- No credentials in any file here. A recorded FIRMS CSV never contains the key
  (it is in the URL, not the response), but check before committing.
- Keep captures small: a handful of rows or one forecast day is enough to prove
  the parser.
- `server/cache/` is gitignored. These files are not.
