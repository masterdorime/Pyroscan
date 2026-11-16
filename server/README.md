# PyroScan server — vertical slice

Status: the **import path is verified end to end** on the Brighton ODM task.
The watcher and NodeODM client are wired but have not yet been exercised on a
brand-new flight.

```
photos ──► NodeODM ──► DSM + ortho ──► assets ──► fusion ──► spread ──► advisory ──► SQLite
                                                                                       │
                                                        FastAPI + SSE ◄────────────────┘
                                                              │
                                                   Cesium dashboard
```

## Run

```powershell
# offline checks (fusion, spread, advisory, DB)
python -m server.selftest

# import the existing Brighton ODM task into SQLite + mission assets
python -m server.import_mission
python -m server.import_mission --llm        # optional: real qwen3.5:4b advisory

# API + dashboard (same origin, no CORS issues)
python -m uvicorn server.api:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000/dashboard.html

# folder watcher (polls spike/inbox)
python -m server.watcher --interval 5
```

## Data

| Path | Contents |
|---|---|
| `server/pyroscan.db` | SQLite: mission, hotspot, prediction, weather, advisory |
| `spike/missions/<id>/heightmap.json` | 384² DSM derived from ODM |
| `spike/missions/<id>/ortho.webp` | downsampled, contrast-boosted ortho |
| `spike/missions/<id>/ortho_shaded.webp` | ortho multiplied by hillshade |
| `spike/missions/<id>/spatial_fusion.json` | contract v1.1.0 |
| `spike/missions/<id>/advisory.json` | advisory + audit |
| `spike/inbox/` | drop a folder of geotagged photos; watcher picks it up |
| `server/cache/weather.json` | offline weather cache |

## Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/v1/health` | DB / NodeODM / Ollama status |
| GET | `/api/v1/missions` | mission list |
| GET | `/api/v1/missions/latest` | dashboard payload |
| GET | `/api/v1/missions/{id}` | dashboard payload |
| GET | `/api/v1/missions/{id}/fusion` | `spatial_fusion.json` |
| GET | `/api/v1/missions/{id}/advisory` | advisory contract |
| GET | `/api/v1/missions/{id}/heightmap` | heightmap JSON |
| GET | `/api/v1/missions/{id}/ortho.webp` | orthophoto |
| GET | `/api/v1/missions/{id}/ortho_shaded.webp` | hillshaded orthophoto |
| GET | `/api/v1/missions/{id}/mesh.glb` | textured mesh |
| GET | `/api/v1/missions/{id}/providers` | per-provider status, source, age |
| GET | `/api/v1/missions/{id}/providers/{key}` | one provider result |
| POST | `/api/v1/missions/{id}/providers/refresh` | queue a refresh (202) |
| GET | `/api/v1/missions/{id}/regional_fires` | NASA FIRMS detections in the ring |
| GET | `/api/v1/events` | SSE heartbeat (mission events next) |

## Providers (Phase 1)

Weather and regional fire detections come from free public sources through a
gateway in `server/providers/`. The browser never calls a provider.

| Key | Chain | Key needed | TTL |
|---|---|---|---|
| `weather` | BMKG → Open-Meteo | none | 20 min |
| `regional_fires` | NASA FIRMS NRT | `PYROSCAN_FIRMS_MAP_KEY` | 2 h |

- Cache: `server/cache/providers/<mission_id>/<key>.envelope.json` (gitignored,
  disposable — delete a mission's folder to force a refetch).
- Status is derived on read: `fresh`, `stale`, `offline`, `empty`,
  `unconfigured`, `unavailable`, `error`. A provider that is down returns HTTP
  200 with a non-fresh status, never a 5xx.
- A missing key is `unconfigured`, not an error.
- No cache at all and every source failing → committed fixture, `simulated: true`.
- BMKG needs an `adm4` code. It auto-resolves from
  `server/providers/data/adm4_index.json`, which **ships empty**; until the
  boundary dataset is cleared, BMKG reports `unavailable` and Open-Meteo answers.

```powershell
# one real call per provider (opt-in; skips missing keys)
python -m server.providers.selftest --live

# offline self-check (no network)
python -m server.providers.selftest

# warm a mission's cache before deploying offline
python -m server.providers.prefetch --mission <id>
```

## Verified numbers (Brighton)

- 18/18 aligned, 1.08 px reprojection, 1.64 cm GSD
- 0.71 ha reconstructed area
- severity **MEDIUM** from the engine (fixture said HIGH; the DEM at the hotspot
  is 4.1°, so the vector model produced 14.7 m/min)
- +60 min: 2.09 ha, 15 m/min
- p95 dashboard frame time ~33 ms at 1600×900

## Deviations and known gaps

1. **rasterio is now installed** (1.5.2, cp314 wheel) but nothing in the runtime
   imports it yet — Phase 2 will. Fusion still reads the 256² heightmap with
   numpy for the mission path.
2. **watchdog is not installed.** The watcher polls `spike/inbox` every 5 s.
   Replace with `watchdog` when available.
3. **YOLO is not wired.** The import uses the three fixture hotspots; a new
   inbox mission creates one `MANUAL` centre hotspot. This is the next pipeline
   gap.
4. **Weather is the cached fixture** unless the runner is called with
   `online=True`. The cache + age display work.
5. **Advisory defaults to the template** (engine severity, catalog actions).
   `--llm` calls `qwen3.5:4b-q4_K_M` and falls back to the template on failure.
6. **ODM options require `dsm: true`.** Without it ODM 3.6.2 logs
   `DEM will not be generated`. The client uploads individual images; the zip
   upload failed on NodeODM 3.6.2.
7. **Prediction polygons in Cesium are visual approximations.** The API returns
   points and rates, not front geometry.
8. **No API auth.** LAN/posko only; add a shared token before exposing it.
9. **Processing time** in the imported mission is set to the first full run
   (507 s). `stats.json` was later overwritten by the 2-minute DSM restart.
   Fresh runs report their own time.

