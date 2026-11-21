# Product Requirement Document (PRD) — PyroScan

**Version:** 1.3.1
**Status:** Approved / In Development
**Author:** Tristan Edgina Rakhadewa
**Target Delivery:** MVP Phase

> **Changelog 1.3.1** — Real LLM benchmark on the RTX 4060 Laptop; default model becomes `qwen3.5:4b-q4_K_M`; `severity` is moved out of the LLM. See §10.

---

## 1. Executive Summary & Objective

**PyroScan** is a forest-fire monitoring, 3D mapping, and spread-prediction system built on *edge AI*, *photogrammetry*, and an *LLM advisory agent*.

The system uses an *extension payload* — a **used Android phone (Realme 3 Pro)** mounted under the drone's belly — to capture geotagged photos (GPS EXIF) and detect fire/smoke in flight. Once landed, the photos are synced to the **Ground Command Laptop (Lenovo LOQ, RTX 4060, i7-HX)**, processed into orthophoto and DEM, fused with weather data and slope analysis to detect hotspots and predict fire movement 30–60 minutes ahead, and presented as an interactive **CesiumJS** dashboard plus a narrative report from **Qwen3.5-4B**.

### 1.1. Two Mission Modes

PyroScan supports **two operating modes** from the MVP onward. Both share the payload, pipeline, and dashboard — only the interpretation of results and the prediction method differ.

| Mode | When used | Input | Output |
|---|---|---|---|
| **MODE-A: Pre-Fire Monitoring** | Ahead of the fire, over unburned terrain | Live canopy photos + YOLO hotspots + DEM | Fuel/terrain map, slope, predicted spread vector |
| **MODE-B: Burn-Scar Mapping** | After the fire | Burned-surface photos + DEM | Burned area, last fire boundary, post-burn relief |

**Why two modes:** a living canopy is the worst possible subject for SfM feature matching — repetitive texture, homogeneous, moving in the wind. A burned surface is rich in texture and static. Supporting MODE-B gives the project a guaranteed success path if MODE-A fails in the field, and MODE-B produces the burned-area figure that can validate MODE-A afterwards.

### 1.2. Design Principles

1. **One photogrammetry container, no web app.** The pipeline calls **NodeODM** directly over REST. WebODM (Django + PostGIS + bundled UI) is not used; the management UI is built into the dashboard so it stays visually consistent.
2. **Measured, not assumed.** `qwen3.5:4b-q4_K_M` measured at 67 t/s / 11.4 s / 3.97 GB and clears the latency KPI by 7.9×. A 9B model is considered only if it proves better at narrative. *Thinking* is disabled. `severity` is never produced by the LLM (§5.2 FR-SRV-06a).
3. **Just enough terrain.** A 100×100 m mission is rendered from a local heightmap via `CustomHeightmapTerrainProvider`, not a quantized-mesh tileset.
4. **GPU serialization.** Photogrammetry and the LLM **must not** occupy VRAM at the same time on 8 GB.
5. **No second language.** Python for the pipeline, TypeScript for the UI. No Rust, no extra services.

---

## 2. Hardware Baseline Specifications

### 2.1. Edge Payload Module (Airborne)
* **Device:** Realme 3 Pro (custom PETG 3D-printed enclosure + rubber damper).
* **SoC / Compute:** Qualcomm Snapdragon 710 (10nm), Adreno 616 GPU, Hexagon 685 DSP.
* **Camera Sensor:** 16 MP Sony IMX519 ($f/1.7$, EXIF geotagging via multi-GNSS GPS/GLONASS/Galileo).
* **Connectivity:** Local Wi-Fi (Phase 1). USB-C OTG serial to the ESP32 LoRa transmitter (Phase 2).
* **Camera2 level:** **must be verified** (`INFO_SUPPORTED_HARDWARE_LEVEL`). On Android 9/10 the Realme 3 Pro is likely `LEGACY`/`LIMITED`, so manual exposure control and frame rate may be constrained. See `hardware_specifications_pyroscan.md` §8.

### 2.2. Ground Station Server (Command Post)
* **Device:** Lenovo LOQ laptop.
* **CPU:** Intel Core i7 HX-series (high-performance multi-core).
* **GPU:** NVIDIA GeForce RTX 4060 8 GB GDDR6 (CUDA) — *laptop SKU, 128-bit bus (~256 GB/s), 80–115 W, thermal throttling expected*.
* **RAM:** 16 GB / 32 GB DDR5.
* **OS environment:** Windows 11 / Ubuntu via WSL2, Docker Desktop, Ollama runtime.

### 2.3. VRAM Budget (8 GB — hard constraint)

Measured on the actual hardware (RTX 4060 Laptop, 8188 MiB). See `llm_benchmark_pyroscan.md`.

| Component | VRAM | Source | Concurrent? |
|---|---|---|---|
| NodeODM / OpenSfM feature extraction | ~2–4 GB | estimate | ❌ serial |
| `qwen3.5:4b-q4_K_M` @ `num_ctx=8192` | **3.97 GB** | **measured** | ❌ serial |
| `qwen3.5:9b` Q4_K_M @ `num_ctx=8192` | ~5.9 GB | estimate | ❌ serial |
| `gemma4:e4b` @ `num_ctx=8192` | 4.41 GB | measured | ❌ serial |

**Rule:** the pipeline **must** run photogrammetry and the LLM in sequence. `OLLAMA_KEEP_ALIVE=0` is set so the model releases VRAM after generation. Usable VRAM is ~7.2 GB (not 8), so 3.97 + 2–4 GB only fits if serialized.

---

## 3. Target Users & Use Cases

### Target Users
1. **Disaster Command Post Commander / SAR Team:** needs fast decisions on evacuation routes and vegetation-break points (*firebreak*).
2. **Field Drone Operator:** needs a compact payload that collects data automatically without interfering with flight.

### Key Use Cases
* **UC-00 (Pre-Flight Verification):** the operator verifies camera, GNSS fix, and thermal state before takeoff via a pre-flight check page in the dashboard.
* **UC-01 (Post-Flight 3D Mapping):** bulk-copy photos over the local Wi-Fi to the Lenovo LOQ, then process with GPU CUDA **NodeODM** into a 3D terrain model, orthophoto, and DEM.
* **UC-02 (Burn-Scar Quantification — MODE-B):** from burned-area photos, compute burned area, last fire boundary, and post-burn relief.
* **UC-03 (Fire Spread Simulation — MODE-A):** compute the fire's speed and direction vector from slope and wind.
* **UC-04 (Offline LLM Executive Advisory):** generate an automatic narrative report using `qwen3.5:4b-q4_K_M` (local on the RTX 4060) covering risk level and recommended SAR actions.
* **UC-05 (In-Flight Pinpoint Alert — Phase 2):** transmit hotspot pinpoints from the Realme 3 Pro over LoRa (16-byte payload) while the drone is still airborne. *The data contract is defined now; implementation is deferred (§9 DG-02).* **LoRa's only role is marking a YOLO pinpoint — it is not the data exchange channel.**

---

## 4. System Architecture & Data Flow

```
[ Drone Payload: Realme 3 Pro (Snapdragon 710) ]
   ├── Camera2 12MP default (16MP max) ──> auto-geotagged EXIF photos
   ├── On-device TFLite ──> hotspot log (on-device, Phase 1)
   ├── [Phase 2] LoRa 16-byte pinpoint via ESP32/SX1262 (YOLO detections only)
   └── Foreground service (camera type) + local storage
            │
            ▼ (bulk transfer post-landing over Wi-Fi to the command-post router)
[ Ground Station: Lenovo LOQ (i7-HX + RTX 4060 8GB) ]
   ├── Directory watcher (watchdog)   ──> SQLite mission row
   ├── NodeODM Docker (CUDA)          ──> ortho.tif + dem.tif + mesh.glb
   ├── YOLOv8 (server-side verify)    ──> hotspot list
   ├── Mission Mode Resolver          ──> MODE-A / MODE-B
   ├── Spatial Fusion (rasterio)      ──> spatial_fusion.json
   ├── Spread Simulation (numpy)      ──> prediction vectors  [MODE-A]
   ├── Burn Metrics (numpy/rasterio)  ──> scar area, perimeter [MODE-B]
   └── Ollama qwen3.5:4b-q4_K_M       ──> advisory JSON  [serial, GPU]
            │
            ▼  FastAPI + SSE
[ Dashboard Frontend (CesiumJS + React + Vite + Tailwind) ]
   ├── Photogrammetry Manager (upload, progress, result preview)
   ├── CustomHeightmapTerrainProvider (local DEM)
   ├── SingleTileImageryProvider (local orthophoto)
   ├── Hotspot pins + prediction vector arrows
   ├── Burn-scar polygon overlay  [MODE-B]
   └── Advisory panel + weather widget
```

---

## 5. Functional Requirements

### 5.1. Edge Payload Module (Android app on the Realme 3 Pro)
* **FR-PAY-01:** The app runs as a **foreground service** of type `camera`, capturing on a configurable interval ($2–4\text{ s}$ default). Default resolution **12 MP**, maximum 16 MP.
* **FR-PAY-02:** The app injects GPS coordinates ($Lat, Lon, Alt$) and the GNSS timestamp into the EXIF of every JPEG.
* **FR-PAY-03 (Delegate fallback chain):** runs **YOLOv8n TFLite (INT8)** inference through a fallback chain that is **measured, not assumed**: `NNAPI` → `GPU delegate (FP16)` → `XNNPACK CPU (INT8)`. The fastest stable delegate found at startup is selected and logged. **NNAPI is not required to succeed** — on the Snapdragon 710 it frequently splits the graph and ends up slower than XNNPACK.
* **FR-PAY-04:** Persists every detection to a local log (CSV/JSON) with timestamps, so no data is lost if a transfer fails.
* **FR-PAY-05 (Operator SOP):** because ColorOS aggressively kills background services, the app must provide an onboarding screen covering camera + background location permission, battery-optimization exemption, and autostart permission.
* **FR-PAY-06 (Phase 2):** transmits the 16-byte telemetry frame over USB-C OTG to the ESP32 LoRa transmitter. Data contract in `data_contracts_api_schema_pyroscan.md` §1.

### 5.2. Ground Station Pipeline (Lenovo LOQ RTX 4060)
* **FR-SRV-01 (Directory watcher):** detects new photo files (`watchdog`) and creates or resumes the `mission` row in SQLite.
* **FR-SRV-02 (CUDA photogrammetry — NodeODM):** triggers **NodeODM** (single container, REST API) with explicit options: `use-exif: true`, `gps-accuracy: 15`, `resize-to: 2000`, `feature-quality: medium`, `pc-quality: medium`, `orthophoto-resolution: 2`. Outputs: `odm_orthophoto.tif`, `odm_dem.tif`, `odm_textured_model_geo.glb`.
* **FR-SRV-03 (Spatial fusion engine):** reads elevation/slope/aspect from the DEM `.tif` via `rasterio` at the hotspot coordinates. Produces `spatial_fusion.json`.
* **FR-SRV-04 (Fire spread simulation — MODE-A):** projects fire position 30–60 minutes ahead from the wind vector (Open-Meteo, with the last offline cache) and slope push (*Rothermel-inspired slope factor*). `slope_weight` / `wind_weight` **must be configurable** (calibration in Phase 3).
* **FR-SRV-05 (Burn metrics — MODE-B):** computes burned area, perimeter, and bounding box from burned-surface classification on the orthophoto. The output feeds the dashboard polygon layer and serves as ground truth for MODE-A calibration.
* **FR-SRV-06 (Local LLM copilot):** sends the spatial JSON to the model via the local Ollama API and requests structured JSON. Mandatory parameters: `num_ctx=8192`, `think: false`, `OLLAMA_KEEP_ALIVE=0` (all **measured**; see `llm_benchmark_pyroscan.md`). Runs **after** photogrammetry finishes.
  * **FR-SRV-06a:** `severity` **must not** be produced by the LLM. It comes from the deterministic simulation engine and is passed through unchanged. The LLM fills only `summary_narrative` and `action_items`. Reason: in the benchmark, `qwen3.5:4b` escalated `HIGH` (from the engine) to `CRITICAL` — two missions with identical data could otherwise report different threat levels.
  * **FR-SRV-06b:** `action_items` is validated post-generation against an allowed action vocabulary (evacuation, firebreak, route, coordination). Items outside the list are dropped, not displayed.
  * **FR-SRV-06c:** every advisory is stored with `model`, `prompt_sha`, and `seed` for audit, and shown in the dashboard with a **"draft — verify in the field"** label.
* **FR-SRV-07 (Persistence):** all mission state, hotspots, predictions, weather observations, and advisories are stored in **SQLite** (`pyroscan.db`).
* **FR-SRV-08 (API layer):** **FastAPI + uvicorn** on the command-post LAN serves REST + SSE for mission progress. No Redis, no Celery.

### 5.3. Admin Dashboard (Frontend)
* **FR-DSH-01:** renders 3D terrain with **CesiumJS** using a `CustomHeightmapTerrainProvider` built from `odm_dem.tif`. No quantized-mesh tileset, no Cesium ion.
* **FR-DSH-02:** places interactive 3D pinpoints for the **active fire** (red pin) and the **1-hour prediction** (orange pin) with a spread vector arrow.
* **FR-DSH-03:** shows an *Advisory Panel* with the narrative produced by `qwen3.5:4b`.
* **FR-DSH-04:** provides a *Weather Widget* (wind speed, wind direction, temperature, humidity) with a data-age indicator.
* **FR-DSH-05 (Masking & culling):** the orthophoto and Cesium mesh must be masked to the mission coverage area. Without this, Cesium renders the whole globe and wastes frame time outside the 100×100 m patch.
* **FR-DSH-06 (Fallback):** if the DEM/mesh is not ready, the dashboard shows a 2D basemap + hotspot pins + a pipeline status banner.
* **FR-DSH-07 (Photogrammetry Manager):** one page to pick a photo folder, start an ODM task, watch progress over SSE, and preview results (orthophoto, DEM, mesh, aligned photo count). Replaces WebODM's built-in UI.

---

## 6. Non-Functional Requirements

* **NFR-PERF-01 (Payload weight):** the total weight of the extension module (Realme 3 Pro without back cover + 3D-printed casing + ESP32 + antenna + dampers) must not exceed **190 g**. Breakdown in `hardware_specifications_pyroscan.md` §6.
* **NFR-PERF-02 (Processing time):** with `resize-to: 2000` and `feature-quality: medium`, processing **30 photos @12 MP over 100×100 m** from landing to 3D render must finish in **< 4 minutes**. This figure **must be validated on real hardware** before it becomes a commitment; 50 photos @16 MP at default quality is expected to exceed the target substantially.
* **NFR-RELI-01 (Offline operation):** the command-post server and dashboard operate **100% offline** — local NodeODM, local Ollama, terrain and orthophoto served from local files. No dependency on Cesium ion, CDNs, or public tile servers.
* **NFR-RELI-02 (GPU serialization):** the pipeline must guarantee photogrammetry and the LLM never occupy VRAM simultaneously. Violating this produces OOM, not degraded performance.
* **NFR-SEC-01 (Data integrity):** GPS data and the flight log are stored in parallel on the phone's internal storage and the laptop SSD to prevent data loss if the drone crashes.
* **NFR-COST-01 (Zero recurring cost):** no paid service (cloud compute, tile hosting, LLM API) on the operational path.
* **NFR-MAINT-01 (Two languages only):** Python for the pipeline, TypeScript for the UI. No additional service, runtime, or language on the critical path.

---

## 7. Success Metrics (KPIs)

Only metrics with a **clear measurement procedure** and an **actual data source** are retained. Aspirational metrics without a validation method were removed (see §10).

| KPI | Measurement procedure | Minimum target (MVP) |
|---|---|---|
| **YOLOv8 fire/smoke detection** | mAP50 against a held-out field validation set | $> 80\%$ |
| **Aligned photos (SfM success rate)** | `num_reconstructed` ÷ `num_images` from the NodeODM report | $> 80\%$ MODE-B, $> 60\%$ MODE-A |
| **End-to-end processing time** | `time` from watcher trigger → all artifacts in SQLite | $< 4\text{ min}$ (30 photos @12 MP) |
| **Relative orthophoto accuracy** | RMSE between ≥ 3 ground GCP checkpoints | $< 2\text{ m}$ |
| **Hotspot position error** | Distance between pin and manually measured ground-truth fire position | $< 15\text{ m}$ |
| **Dashboard frame time** | p95 frame time @ 1080p, Cesium render loop, 60 s sampling | $< 33\text{ ms}$ |
| **Advisory latency** | From ODM status `DONE` → advisory JSON stored | $< 90\text{ s}$ (**measured 11.4 s**) |

> **Removed from v1.1.0:** "60 FPS" (not a single metric — replaced by p95 frame time), "EXIF accuracy < 5 m" (not guaranteeable from single-band GNSS while moving — replaced by relative accuracy + hotspot error), "LLM > 15 tokens/s" (not a product success indicator; still measured in the benchmark but not a KPI).

---

## 8. Phased Roadmap

### Phase 0: Technical Spike (gate — before writing production code)
* **SPIKE-01 (Blocking / DG-01):** capture 20–30 nadir photos from the phone at operating altitude above a **living forest canopy**. Run photogrammetry. Measure: aligned-photo percentage, reprojection RMSE, processing time.
  * If alignment fails ≥ 60% → MODE-A is not viable; the product moves to MODE-B as the primary mode. **The decision is made before Phase 1 writes pipeline code.**
* **SPIKE-02:** verify `INFO_SUPPORTED_HARDWARE_LEVEL`, Camera2 exposure control, and rolling shutter on the Realme 3 Pro.
* **SPIKE-03:** benchmark the three TFLite delegates on the device; record FPS and temperature after 10 minutes of continuous capture.
* **SPIKE-04:** benchmark `qwen3.5:4b` against alternatives on the laptop: tok/s, peak VRAM, Indonesian quality. Record the results in this document as a measured table.
* **SPIKE-05:** confirm a fire/smoke YOLO dataset exists and that its licence suits the intended use (Ultralytics = AGPL-3.0).
* **SPIKE-06:** verify Indonesian LoRa frequency regulation (DG-02) — only if LoRa is enabled in Phase 2.

### Phase 1: MVP Core (current focus)
* Android capture app with EXIF GPS foreground service on the Realme 3 Pro.
* Python pipeline: `watchdog` + NodeODM Docker CUDA + YOLOv8 + fusion + spread simulation + burn metrics.
* SQLite + FastAPI (REST + SSE).
* React + CesiumJS dashboard: heightmap terrain, hotspot pins, prediction arrows, burn-scar polygon, advisory panel.
* Photogrammetry Manager (FR-DSH-07) replacing the WebODM UI.
* YOLOv8n fire & smoke training/evaluation (an explicit workstream).
* Validate the §7 KPIs on real hardware; revise the figures if they miss.

### Phase 2: Hardware Integration & LoRa
* Serial USB OTG from the Realme 3 Pro → ESP32 LoRa (SX1262) + command-post receiver. **Pinpoint only**, and only once DG-02 clears and the drone is confirmed to have no telemetry link of its own.
* Final 3D-printed enclosure + weight and damper verification.

### Phase 3: Field Testing & Calibration
* Field testing with a real drone flight (MODE-A and MODE-B).
* Recalibrate `slope_weight` vs `wind_weight` in the spread vector model, using MODE-B burn-scar area as the reference.
* Calibrate `gps-accuracy` and GCP placement.

---

## 9. Risk Register & Decision Gates

| # | Risk | Impact | Status | Mitigation |
|---|---|---|---|---|
| R-01 | **SfM fails over a living canopy** | Fatal for MODE-A | **DG-01, blocking** | SPIKE-01. If it fails, MODE-B becomes the primary mode and MODE-A is an explicitly marked experimental feature in the UI. |
| R-02 | **Processing-time target not met** | High | Open | Reduce ODM resolution/quality, measure for real, revise NFR-PERF-02 before promising it. |
| R-03 | **8 GB VRAM insufficient for ODM + LLM** | High | Mitigated by NFR-RELI-02 | Serialize the pipeline, `OLLAMA_KEEP_ALIVE=0`, 4B model. |
| R-04 | **ColorOS kills the background service** | High | Open | FR-PAY-05 onboarding SOP + field verification. |
| R-05 | **NNAPI slower than CPU** | Medium | Mitigated by FR-PAY-03 | Measured fallback chain. |
| R-06 | **Phone GNSS cannot reach high absolute accuracy** | Medium | Mitigated by KPI §7 | Measure relative accuracy + GCP checkpoints; never promise absolute. |
| R-07 | **LoRa frequency regulation** | Medium (legal) | **DG-02** | Only relevant if Phase 2 runs. SX1262 can be tuned to 915 or 923 MHz. |
| R-08 | **YOLO dataset unavailable / AGPL licence** | High | Open | SPIKE-05 before writing inference code. |
| R-09 | **Payload thermal load during continuous capture** | Medium | Open | 2–4 s interval, 12 MP, 10-minute continuous test, log throttling. |
| R-10 | **Rolling shutter + drone vibration → motion blur** | Medium | Open | Shutter ≥ 1/1000 s, rubber dampers, field sharpness test. |
| R-11 | **Scope creep from supporting two modes** | Medium | Open | Both modes share one pipeline; the only differences are the metric layer and the UI label. Not two apps, not two databases. |
| R-12 | **Laptop thermal throttling during long ODM runs** | Medium | Open | Measure temperature and clocks; consider Windows power mode and repasting. |

### Decision Gates
* **DG-01 (SfM viability):** passes if ≥ 80% of photos align on MODE-B, or ≥ 60% on MODE-A (living canopy). Fails → MODE-B becomes the primary mode. Owner: Tristan.
* **DG-02 (LoRa):** enabled only if (a) the drone has no usable telemetry link and (b) the final frequency has been verified against regulation. Do not print the enclosure before this gate clears.
* **DG-03 (final LLM):** chosen from SPIKE-04. **Status: partially closed.** Measured on the RTX 4060 Laptop: `qwen3.5:4b-q4_K_M` = 67.1 t/s, 11.4 s wall, 3.97 GB VRAM, valid JSON 3/3 → **production default**. `gemma4:e4b` = 55.9 t/s, not selected. `qwen3.5:9b` and `qwen3-vl:4b` **remain unmeasured** — two download attempts failed (230 KB/s, then `503 upstream connect timeout` from the registry). Reconsider only if their narrative quality proves clearly better while holding > 30 t/s. Details: `llm_benchmark_pyroscan.md`.
* **DG-04 (advisory contract):** ✅ **Closed.** FR-SRV-06a–c implemented and verified live in `server/llm_agent/advisory.py`. `severity` comes from the engine, actions are chosen from a closed catalog, and every advisory has an audit trail. Self-check 10/10.

---

## 10. Changelog

### 1.3.1
* **DG-03 partially closed by real measurement** on the RTX 4060 Laptop 8 GB. Production default becomes **`qwen3.5:4b-q4_K_M`**.
* **FR-SRV-06a–c added:** `severity` is no longer produced by the LLM; `action_items` is validated; advisories carry an audit trail and a draft label. Triggered by benchmark findings (the 4B escalated HIGH→CRITICAL and produced nonsensical actions such as "water barricade").
* **§2.3 VRAM budget** replaced with measured figures.
* **New document:** `Docs/llm_benchmark_pyroscan.md` (method, results, reproduction).
* **New harness:** `benchmarks/bench_llm.py` (stdlib only).
* **`qwen3.5:9b` download failed twice** (230 KB/s, then `503 upstream connect timeout`) — DG-03 remains partial without adequate connectivity.

### 1.3.0
* **Scope:** added the **two mission modes** — MODE-A (pre-fire monitoring) and MODE-B (burn-scar mapping), sharing one pipeline (§1.1). Added FR-SRV-05 Burn Metrics.
* **LLM:** `qwen3.5:9b` (vision-capable, 5.6 GB Q4, Apache 2.0) as default; `qwen3-vl:4b` as fallback. Mandatory `num_ctx=8192` + thinking off. DG-03 added.
* **UI:** NodeODM + a self-built **Photogrammetry Manager** (FR-DSH-07) replacing the WebODM UI. No Rust.
* **KPI:** metrics without a measurement procedure removed (§7). Added "SfM success rate" as a primary KPI.
* **LoRa:** deferred to Phase 2, folded into DG-02. FR-PAY-04 became local logging with no radio.
* **Added:** FR-DSH-05 Cesium masking/culling (performance), SPIKE-04/06, R-11/R-12, NFR-MAINT-01 (two languages only).

### 1.2.0
* WebODM → **NodeODM**. Qwen2.5-VL-7B → a text model (later revised in 1.3.0).
* Terrain tiling → `CustomHeightmapTerrainProvider`. `.b3dm` output removed.
* Added SQLite, FastAPI + SSE, VRAM budget, NFR-RELI-02, NFR-COST-01.
* Payload: 2–4 s interval, 12 MP default, foreground service + ColorOS SOP, NNAPI fallback chain.
* Roadmap: added Phase 0 Technical Spike.

### 1.1.0
* Initial approved version.
