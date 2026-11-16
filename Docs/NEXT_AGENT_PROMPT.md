# Next Agent Prompt — PyroScan Free Provider Layer

You are the next agent on **PyroScan**. Do not rely on the previous chat
context. Read, in order:

1. `Docs/HANDOFF.md`
2. `Docs/dashboard_design.md`
3. This prompt
4. `README.md` and `server/README.md`

**Repo:** https://github.com/masterdorime/Pyroscan (public, `main`).
Check `git log -1` for the current commit. The working tree is clean except for
an untracked `benchmarks/` folder.

## What is done

- ODM photogrammetry pipeline, SQLite, FastAPI, advisory, watcher.
- Dashboard: paper/obsidian themes, incident header/card rail, theme dropdown,
  elevation chart, bright paper landscape.
- **Context → Reconstruction** view: Context is the default basemap + footprint
  disc + hotspot pins; click/zoom opens the patch; Context pill/minimap/zoom-out
  returns.
- Pushed to the repo. Raw `spike/data/` (2.17 GB), `spike/ref/` video,
  `node_modules/`, and `opencode.json` are gitignored. `opencode.json` contains a
  local agent API key — **never commit it**.
- The previous API/static servers were stopped by a restart. Start them with
  `Docs/HANDOFF.md` §2 before testing.

## Current objective

Plan the **free provider layer** and write the spec. **Do not implement
providers yet.** This is architectural work; follow the brainstorming →
spec → user review → writing-plans sequence.

## Locked decisions

- **Indonesia-first**; Brighton remains the demo.
- **Hybrid live refresh**: fetch when online, always serve cache, show
  source/age/stale. No paid APIs.
- **Mission + 10–25 km regional ring** cache footprint.
- **Auto-resolve BMKG `adm4`** from a bundled Indonesian level-4 boundary/code
  index; manual `adm4` fallback; Open-Meteo fallback.

## Planned providers

| Provider | Role | Key/account | Cost |
|---|---|---|---|
| BMKG | Indonesian weather/wind primary | none; needs `adm4` | free |
| Open-Meteo | global weather/wind fallback | none (non-commercial) | free |
| NASA FIRMS | regional active fire (NRT) | free `MAP_KEY` | free |
| Copernicus DEM | context terrain (30 m) | none (AWS Open Data) | free |
| Sentinel-2 | context imagery (10 m) | none on AWS; free CDSE account optional | free |
| OSM / Photon | roads, place labels, reverse geocode | none; public policy/self-host | free |
| ODM / Ollama | existing reconstruction/advisory | none | local |

Keys/accounts go server-side in `.env`; never in the browser or repo. FIRMS
needs a free `MAP_KEY`; NASA Earthdata/Copernicus Data Space need free accounts
only if used.

## Recommended architecture

**Provider gateway inside FastAPI + file cache** (recommended):
- `server/providers/` with one adapter per source.
- Shared `ProviderResult`: `data`, `source`, `observed_at`, `fetched_at`,
  `age`, `status`, `error`, `licence`.
- Cache under `server/cache/providers/<mission>/`; TTLs: weather 15–30 min,
  FIRMS 1–3 h, Sentinel 1–5 days, DEM/OSM 30–90 days.
- Hybrid refresh via FastAPI background tasks or a small CLI prefetch. No
  Redis/Celery.
- API: `GET /api/v1/missions/{id}/providers`; payload additions for
  `regional_fires`, `context_dem`, `context_imagery`, `places`.
- UI: Live-data source/age card, regional FIRMS layer/inset, context DEM and
  Sentinel-2 imagery, OSM labels/place card.
- Label real satellite fire `NASA FIRMS · NRT`, not `SIMULASI`.

Rejected: browser direct provider calls (keys/CORS/terms/offline). A separate
data-pipeline service can be a prefetch step for heavy DEM/Sentinel/OSM.

## Phases

1. Provider framework + BMKG/Open-Meteo + FIRMS + source/age. FIRMS first as a
   regional card/inset until the regional map exists.
2. Copernicus DEM + regional context terrain.
3. Sentinel-2 context imagery; replace the Esri prototype basemap.
4. OSM/Photon labels + coordinate place card.
5. Hardening: stale/offline states, provider fixtures, failure tests,
   attribution, storage.

## Risks / open questions

- **BMKG `adm4`**: verify an open level-4 boundary/code dataset, its licence,
  and clean code mapping. Manual `adm4` + Open-Meteo is the safety valve.
- Sentinel-2 clouds/revisit; use windowed COG reads, not full-tile downloads.
- OSM public tile/Nominatim limits; self-host for production.
- Esri is prototype-only; replace for a free public deployment.
- Hybrid mixed-age data: source/age/stale UI is mandatory.
- Per-mission ring storage ~30–100 MB; no GPU for providers; ODM remains the
  hardware bottleneck.
- Coordinate hover readout is **not implemented**. It is local Cesium math, but
  absolute accuracy is limited by drone GPS and basemap registration; do not
  imply survey accuracy or add 6-decimal false precision. OSM/Photon later
  supplies place names for a Google-like card.

## Next action

1. Write `Docs/specs/2026-11-16-free-provider-layer-design.md` with:
   provider interfaces, data contracts, cache layout/TTLs, refresh/fallback,
   keys, API/UI states, phases, tests, risks, and acceptance criteria.
2. Self-review the spec for placeholders, contradictions, ambiguity, scope.
3. Ask the user to review it. **Do not start implementation before approval.**
4. After approval, use `writing-plans`, then implement Phase 1.
5. Keep `Docs/HANDOFF.md` and screenshots in sync; commit/push docs.

## Guardrails

- No paid APIs or paid keys.
- No secrets in the browser or repo; `.env` only, gitignored.
- Do not rebuild the ODM pipeline or replace the Context/Reconstruction flow.
- Do not commit raw `spike/data/`, `spike/ref/`, `node_modules/`, or
  `opencode.json`.
- The dashboard fallback must keep working offline.
