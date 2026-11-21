# AGENTS.md — PyroScan

**Status:** accurate as of 2026-11-21. Supersedes `Docs/agents_guidelines_pyroscan.md` (deleted).

**Read in order, do not skip:**
1. This file — rules and repo map.
2. `Docs/HANDOFF.md` — engineering state. **§9 is the authoritative gap list.**
3. `Docs/dashboard_design.md` — visual system.
4. `Docs/data_contracts_api_schema_pyroscan.md` — data contracts.

Do not rebuild the pipeline. It works.

---

## 1. What this is

An offline forest-fire mission console: a drone payload (an Android phone) photographs the terrain → photogrammetry → 3D map + DEM/weather fusion → spread prediction → advisory → dashboard.

**The payload is the actual product.** The dashboard is supporting infrastructure, and it is far more mature than the payload.

## 2. Hard rules

- **Offline on the critical path.** No CDN, no Cesium ion, no Google tiles. Cesium 1.147 is bundled under `spike/web/cesium/`. Every runtime request is local.
- **Two languages only:** Python (`server/`), JavaScript (`spike/web/`). There is no React/Vite port — do not start one unasked.
- **One interface, one owner:** `spatial_fusion.json`, the `server/db.py` schema, the advisory contract. Changes from anyone else go through the owner.
- **GPU:** ODM and the LLM must never hold VRAM at the same time. `OLLAMA_KEEP_ALIVE=0`.
- **Accuracy:** never claim sub-5 m absolute accuracy from phone GNSS. The honest claims are relative accuracy and hotspot position error.
- **Data labelling:** anything still a fixture must read `SIMULASI`. Anything real must name its source (`NASA FIRMS · NRT`, `BMKG`, `Sentinel-2`).

## 3. Repo map

```
server/api.py                     FastAPI + SSE + static dashboard (the only door to the browser)
server/db.py                      SQLite; sole owner of the schema
server/pipeline/                  runner → assets → fusion → spread → advisory
server/providers/                 one adapter per source + Gateway + cache/TTL + selftest
server/photogrammetry/nodeodm.py  the only door to NodeODM
server/watcher.py                 polls spike/inbox
server/llm_agent/advisory.py      advisory contract (engine severity + closed action catalog)
spike/web/                        dashboard (map2d.js for Indonesia, Cesium for 3D)
spike/missions/<id>/              prebuilt mission assets
spike/data/                       raw drone data (not committed)
simulation/                       payload 3D studio — a visual prototype, NOT the enclosure
Docs/archive/                     archived proposals/budget. Do not treat as reference.
```

`hardware/` does not exist yet. The enclosure has not been modelled.

## 4. Current state (2026-11-21)

**Running and verified:** `python -m server.selftest` PASS · `python -m server.providers.selftest` **113/113** · `node spike/web/test-terrain-math.mjs` PASS.

**Proven on real data (Brighton ODM):** 18/18 images aligned, 1.08 px RMSE, 1.64 cm GSD, 0.71 ha, one mission `DONE` in SQLite.

**Provider layer:** weather (BMKG → Open-Meteo), FIRMS, Copernicus DEM 30 m, Sentinel-2, plus wide variants. All reads come from cache, status is derived on read (`fresh`/`stale`/`offline`/`empty`/`unconfigured`/`unavailable`/`error`), and the browser never calls a provider directly.

**View modes:** `Indonesia` is a Canvas 2D map (`map2d.js`; the globe is retired), four skins. `Drone`/`Terrain`/`Regional` use Cesium.

**Still fixtures / SIMULASI:** heat, wind vectors, prediction geometry, severity, YOLO hotspots.

**Not built at all:** Android app, YOLO, enclosure, LoRa, mission-progress SSE (heartbeat only), auth, React port.

## 5. Commands

```powershell
python -m server.selftest                          # fusion, spread, advisory, DB
python -m server.providers.selftest                # 113 checks, no network
python -m server.providers.selftest --live         # one real call per provider
python -m server.import_mission                    # import the existing ODM task
python -m server.import_mission --llm              # advisory via qwen3.5:4b
python -m uvicorn server.api:app --host 127.0.0.1 --port 8000
node spike/web/test-terrain-math.mjs               # the DEM maths every surface depends on
python -m server.providers.prefetch --mission <id> # warm the cache before going offline
```

Python 3.14 · Node 24 · NodeODM 3.6.2 · Ollama 0.40.5 + `qwen3.5:4b-q4_K_M` · Cesium 1.147 bundled.

## 6. Contracts that must not change quietly

- **`spatial_fusion.json` v1.1.0** — the single input to the simulation engine and the advisory.
- **Advisory** — `severity` comes from the simulation engine and **never** from the LLM. Actions are chosen from a closed catalog, the rendered text comes from that catalog, and every advisory carries `audit` (model, prompt_sha, seed, dropped_ids). See `server/llm_agent/advisory.py`. The model is measured: `qwen3.5:4b-q4_K_M`, 67 t/s, 11.4 s, 3.97 GB (`Docs/llm_benchmark_pyroscan.md`).
- **LoRa 16-byte frame** — `lat`/`lon` int32 × 1e7, `alt` int16, `fire_conf`/`smoke_conf` uint8, `timestamp` uint32, little-endian. **Its only job is to mark a YOLO pinpoint while the drone is still flying.** It is not a data exchange channel; photos still arrive over Wi-Fi after landing.

## 7. Payload — the main workstream, not started

None of the following exists yet:

- **Enclosure:** tray + four damper mounts + 30×20 camera window + ESP32 pocket + antenna mount. PETG, 15–20% infill. **Weighed, target < 190 g.**
- **Android app:** `camera`-type foreground service, Camera2, 2–4 s interval, 12 MP, GPS EXIF, one folder per mission, preflight screen (Camera2 level, GNSS fix, battery temperature, free storage), Wi-Fi transfer into the inbox.
- **On-device detection:** YOLO → TFLite INT8. Delegates are **measured**, not mandated (`NNAPI` → GPU delegate → XNNPACK CPU).
- **LoRa:** ESP32 TX/RX firmware + serial bridge → `/lora/ingest`. The module has not been purchased.

Field notes that are expensive to forget:
- A 300 g damper rating is too stiff for a 190 g payload — vibration isolation gets worse, not better.
- USB OTG host mode means the phone **cannot charge** in flight; mission length is capped by phone battery.
- A belly mount shifts the drone's CG — hover-test before a full mission.
- The Realme 3 Pro's Camera2 level is probably `LEGACY`/`LIMITED`; check `INFO_SUPPORTED_HARDWARE_LEVEL` before designing the enclosure.

## 8. Do not

| Do not | Why |
|---|---|
| Put WebODM on the critical path | Django + PostGIS + an unused UI; NodeODM is enough |
| Use Rust | There is no SfM/MVS in Rust; Cesium is JS |
| Add Redis / Celery / Postgres | One operator, one laptop |
| Use `resium` | It lags Cesium versions |
| Use Cesium ion / CDNs / Google tiles | Breaks the offline requirement |
| Let the LLM decide `severity` | It measurably escalated HIGH → CRITICAL |
| Claim a frame rate from feeling | Measure p95 frame time |
| Write unmeasured numbers into docs | This is PRD v1.1.0's mistake; v1.3.x replaced them with measurements |

## 9. When you change behaviour

Update `Docs/HANDOFF.md` §9 (gaps) and `README.md` (the first thing anyone reads). Put new screenshots in `Docs/references/`. Never let a document assert something that is no longer true — that has already happened once and it cost time.
