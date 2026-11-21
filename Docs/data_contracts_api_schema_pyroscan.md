# API & Data Schema Specification — PyroScan

**Version:** 1.1.0
**Target:** Edge Payload, Server Pipeline, and CesiumJS Dashboard
**Aligned with:** PRD v1.3.1, `server/llm_agent/advisory.py`

> **Changelog 1.1.0** — LoRa lat/lon `float32` → `int32` (1e-7 precision, still 16 B); `spatial_fusion.json` gains `schema_version` + `mission_mode` + `burn_scar`; advisory contract follows the closed action catalog; `.b3dm` endpoint removed; SQLite schema and heightmap contract added. See §7.

---

## 1. LoRa Binary Telemetry Payload (16-Byte Compact Struct)

Used for long-range radio transmission from the ESP32 on the drone to the ground station when there is no cellular signal. **Phase 2** — the contract is defined now so firmware and parser do not have to change twice.

**Purpose:** the frame exists to mark a YOLO-detected fire pinpoint while the drone is still airborne. It is not a data exchange channel — photos still arrive over Wi-Fi after landing.

### 1.1. Byte Structure Layout

| Byte offset | Variable | Type | Scale / unit | Description |
|---|---|---|---|---|
| `0..3` | `lat_e7` | `Int32` | degrees $\times 10^{7}$ | WGS84 latitude |
| `4..7` | `lon_e7` | `Int32` | degrees $\times 10^{7}$ | WGS84 longitude |
| `8..9` | `altitude` | `Int16` | metres | Height relative to takeoff |
| `10` | `fire_conf` | `UInt8` | $0 - 100$ | Fire detection confidence (%) |
| `11` | `smoke_conf` | `UInt8` | $0 - 100$ | Smoke detection confidence (%) |
| `12..15` | `timestamp` | `UInt32` | UNIX epoch (s) | Capture time from GNSS |

**Total: 16 bytes.** Unchanged from v1.0.0.

### 1.2. Why `int32` instead of `float32`

`float32` gives only ~7 significant digits. At latitude -6.9175 (two digits before the decimal point), the remaining precision falls to ~1.1 m *at best* and degrades as the value grows. `int32` scaled by $10^{7}$ gives **1.1 cm** and is exact — without adding a single byte.

Safe range: latitude $\pm 900{,}000{,}000$ and longitude $\pm 1{,}800{,}000{,}000$, both inside `int32` ($\pm 2{,}147{,}483{,}647$).

### 1.3. C++ Data Struct Definition (ESP32 Firmware)

```cpp
struct __attribute__((__packed__)) PyroScanPacket {
    int32_t  lat_e7;       // 4 bytes, degrees * 1e7
    int32_t  lon_e7;       // 4 bytes, degrees * 1e7
    int16_t  altitude;     // 2 bytes, meters
    uint8_t  fire_conf;    // 1 byte,  0-100
    uint8_t  smoke_conf;   // 1 byte,  0-100
    uint32_t timestamp;    // 4 bytes, unix epoch seconds
}; // Total: 16 Bytes
```

### 1.4. Wire Format Rules

* **Endianness: little-endian**, explicit on both sides. Do not rely on the host's `__BYTE_ORDER__` — document it as LE and convert if needed.
* **No application-level CRC.** The SX1262 has hardware CRC; enable it (`radio.setCRC(true)`) and discard failed packets at the radio.
* The timestamp comes from GNSS, not the phone clock. A packet with timestamp `0` must be rejected by the receiver.
* The parser also accepts `RSSI` and `SNR` from the radio and stores them in the `lora_packet` table (§5).

---

## 2. Server Spatial Data Fusion Schema (`spatial_fusion.json`)

The internal exchange format of the command-post server after photogrammetry, YOLO, and weather complete. This is the **only** input to the simulation engine and the LLM advisory.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "PyroScanSpatialFusion",
  "type": "object",
  "required": ["schema_version", "session_id", "mission_mode", "timestamp"],
  "properties": {
    "schema_version": { "type": "string", "const": "1.1.0" },
    "session_id": { "type": "string", "example": "FLIGHT_20261114_001" },
    "mission_mode": { "type": "string", "enum": ["PRE_FIRE", "BURN_SCAR"] },
    "timestamp": { "type": "string", "format": "date-time" },
    "area_coverage_m2": { "type": "number", "example": 10000.0 },
    "photogrammetry": {
      "type": "object",
      "properties": {
        "images_submitted": { "type": "integer", "example": 30 },
        "images_aligned": { "type": "integer", "example": 27 },
        "align_ratio": { "type": "number", "example": 0.9 },
        "rmse_reprojection_px": { "type": "number", "example": 0.68 },
        "odm_task_id": { "type": "string" }
      }
    },
    "hotspots": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "lat", "lon"],
        "properties": {
          "id": { "type": "string", "example": "SPOT_01" },
          "lat": { "type": "number", "example": -6.917500 },
          "lon": { "type": "number", "example": 107.619100 },
          "elevation_m": { "type": "number", "example": 750.5 },
          "slope_deg": { "type": "number", "example": 32.4 },
          "aspect_deg": { "type": "number", "example": 45.0 },
          "fire_confidence": { "type": "number", "example": 0.92 },
          "smoke_confidence": { "type": "number", "example": 0.85 }
        }
      }
    },
    "environmental_data": {
      "type": "object",
      "properties": {
        "wind_speed_kmh": { "type": "number", "example": 24.5 },
        "wind_direction_deg": { "type": "number", "example": 225.0 },
        "humidity_pct": { "type": "number", "example": 38 },
        "temperature_c": { "type": "number", "example": 31.2 },
        "source": { "type": "string", "example": "open-meteo" },
        "observed_at": { "type": "string", "format": "date-time" },
        "age_minutes": { "type": "integer", "example": 12 }
      }
    },
    "spread_prediction": {
      "type": "object",
      "description": "Primary horizon (30-60 min). MODE-A only.",
      "properties": {
        "predicted_lat": { "type": "number", "example": -6.912000 },
        "predicted_lon": { "type": "number", "example": 107.625000 },
        "estimated_arrival_minutes": { "type": "integer", "example": 45 },
        "risk_level": { "type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"] },
        "slope_weight": { "type": "number", "example": 0.6 },
        "wind_weight": { "type": "number", "example": 0.4 }
      }
    },
    "spread_prediction_alt": {
      "type": "array",
      "description": "Additional horizons. Same shape as spread_prediction.",
      "items": { "type": "object" }
    },
    "burn_scar": {
      "type": "object",
      "description": "MODE-B only.",
      "properties": {
        "area_m2": { "type": "number", "example": 4200.0 },
        "perimeter_m": { "type": "number", "example": 310.5 },
        "bbox": { "type": "array", "items": { "type": "number" }, "example": [-6.9182, 107.6181, -6.9161, 107.6206] },
        "geojson_path": { "type": "string", "example": "missions/FLIGHT_20261114_001/scar.geojson" }
      }
    },
    "wind_direction_convention": {
      "type": "string",
      "const": "FROM",
      "description": "wind_direction_deg is the direction the wind blows FROM (meteorological). 225 = wind from the south-west, fire spreads to the north-east."
    }
  }
}
```

> **Trap to avoid:** `wind_direction_deg` uses the **FROM** convention (meteorological). The fire spread vector is the **TO** direction = `wind_direction_deg + 180`. Getting the sign wrong reverses the entire prediction.

---

## 3. Local LLM Advisory Contract

Reference implementation: `server/llm_agent/advisory.py`. This contract is **enforced by code**, not by prompt wording.

### 3.1. Input: only a subset of `spatial_fusion.json`

The LLM receives numbers, **not** `risk_level` as an instruction. `severity` is computed outside the model.

### 3.2. Closed action catalog

| ID | Text rendered into the UI |
|---|---|
| `EVAC_IMMEDIATE` | Evacuate residents immediately from the sector the fire front will cross. |
| `EVAC_ROUTE` | Open an alternate evacuation route away from the spread direction, not along the wind direction. |
| `FIREBREAK` | Build a firebreak on the designated contour ahead of the fire's leading edge. |
| `AERIAL` | Request aerial suppression (water bombing) at the predicted coordinates. |
| `PATROL` | Increase patrol and hotspot monitoring along the predicted path. |
| `EARLY_WARNING` | Activate early warning and cross-agency coordination. |

The model returns only `action_ids`. The text is rendered from this table on the server.

### 3.3. Request to Ollama

```json
{
  "model": "qwen3.5:4b-q4_K_M",
  "prompt": "<see build_prompt()>",
  "stream": false,
  "format": "json",
  "think": false,
  "keep_alive": 0,
  "options": { "num_ctx": 8192, "temperature": 0.2, "seed": 42 }
}
```

### 3.4. Expected model response (never trusted raw)

```json
{
  "summary_narrative": "The fire is moving quickly to the north-east ...",
  "action_ids": ["EVAC_IMMEDIATE", "FIREBREAK", "AERIAL", "PATROL"]
}
```

`severity` and `action_items` are **not** requested from the model. If the model returns them anyway, they are discarded.

### 3.5. Final advisory (what is stored and sent to the UI)

```json
{
  "severity": "HIGH",
  "summary_narrative": "The fire is moving quickly toward -6.912, 107.625 within 45 minutes ...",
  "action_items": [
    "Evacuate residents immediately from the sector the fire front will cross.",
    "Build a firebreak on the designated contour ahead of the fire's leading edge.",
    "Request aerial suppression (water bombing) at the predicted coordinates.",
    "Increase patrol and hotspot monitoring along the predicted path."
  ],
  "action_ids": ["EVAC_IMMEDIATE", "FIREBREAK", "AERIAL", "PATROL"],
  "audit": {
    "model": "qwen3.5:4b-q4_K_M",
    "seed": 42,
    "prompt_sha": "a5b7295ccafc202b",
    "dropped_ids": [],
    "error": null
  }
}
```

**Validation rules (implemented):**

| Condition | Behaviour |
|---|---|
| `severity` from the model ≠ engine | Ignored; the engine value is used |
| `risk_level` outside the enum | → `MEDIUM` |
| `action_ids` contains an unknown id | Goes into `dropped_ids`, not displayed |
| `action_ids` empty after filtering | Falls back to the two highest-priority ids |
| Model-supplied `action_ids` order | Re-sorted to catalog order |
| JSON cannot be parsed | `error: "unparseable_json"`, advisory still carries fallback actions |
| `summary_narrative` empty / not a string | Empty string, `error` unchanged |

---

## 4. REST API (FastAPI)

Base: `http://<command-post-lan>:8000/api/v1`

| Method | Endpoint | Description | Response |
|---|---|---|---|
| `GET` | `/health` | Server, DB, GPU, Ollama status | JSON |
| `GET` | `/missions` | Mission list (paginated) | `Mission[]` |
| `POST` | `/missions` | Create a mission from a photo folder | `Mission` |
| `GET` | `/missions/{id}` | Mission detail + pipeline status | `Mission` |
| `GET` | `/missions/latest` | Latest mission and telemetry | `Mission` |
| `GET` | `/missions/{id}/fusion` | `spatial_fusion.json` | JSON (§2) |
| `GET` | `/missions/{id}/advisory` | Latest advisory | JSON (§3.5) |
| `POST` | `/missions/{id}/advisory` | Regenerate the advisory | JSON (§3.5) |
| `GET` | `/missions/{id}/heightmap` | Terrain heightmap for Cesium | JSON (§6) |
| `GET` | `/missions/{id}/ortho.tif` | Orthophoto GeoTIFF | `image/tiff` |
| `GET` | `/missions/{id}/mesh.glb` | Textured 3D mesh | `model/gltf-binary` |
| `GET` | `/missions/{id}/scar.geojson` | Burn-scar polygon (MODE-B) | `application/geo+json` |
| `GET` | `/events` | **SSE**: mission progress | `text/event-stream` |
| `POST` | `/lora/ingest` | Receive a packet from the serial receiver | JSON |

**Removed from v1.0.0:** `GET /tiles/3d/{z}/{x}/{y}.b3dm`. ODM does not produce 3D Tiles, and converting requires Cesium ion or an extra toolchain that conflicts with NFR-RELI-01. The mesh is served as a single `.glb` and positioned in Cesium with `Model.fromGltfAsync`.

### 4.1. SSE event shape

```
event: mission_update
data: {"mission_id":"FLIGHT_20261114_001","stage":"PHOTOGRAMMETRY","progress":0.62,"message":"Matching 30 images"}

event: mission_update
data: {"mission_id":"FLIGHT_20261114_001","stage":"DONE","progress":1.0,"advisory_id":"ADV-20261114-01"}
```

Stages (`stage`): `CAPTURING` → `PHOTOGRAMMETRY` → `FUSION` → `SIMULATION` → `ADVISORY` → `DONE` | `FAILED`.

---

## 5. SQLite Schema (`pyroscan.db`)

No Postgres, no PostGIS. All timestamps are ISO-8601 UTC.

```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE mission (
  id            TEXT PRIMARY KEY,              -- FLIGHT_20261114_001
  mission_mode  TEXT NOT NULL CHECK (mission_mode IN ('PRE_FIRE','BURN_SCAR')),
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  area_m2       REAL,
  status        TEXT NOT NULL DEFAULT 'CAPTURING'
                CHECK (status IN ('CAPTURING','PHOTOGRAMMETRY','FUSION',
                                  'SIMULATION','ADVISORY','DONE','FAILED')),
  error_message TEXT,
  odm_task_id   TEXT,
  dem_path      TEXT,
  ortho_path    TEXT,
  mesh_path     TEXT,
  photo_dir     TEXT NOT NULL
);

CREATE TABLE hotspot (
  id               TEXT PRIMARY KEY,
  mission_id       TEXT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
  lat              REAL NOT NULL,
  lon              REAL NOT NULL,
  elevation_m      REAL,
  slope_deg        REAL,
  aspect_deg       REAL,
  fire_confidence  REAL,
  smoke_confidence REAL,
  source           TEXT NOT NULL CHECK (source IN ('YOLO','LORA','MANUAL')),
  detected_at      TEXT NOT NULL
);
CREATE INDEX idx_hotspot_mission ON hotspot(mission_id);

CREATE TABLE prediction (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  hotspot_id      TEXT NOT NULL REFERENCES hotspot(id) ON DELETE CASCADE,
  horizon_min     INTEGER NOT NULL,
  predicted_lat   REAL NOT NULL,
  predicted_lon   REAL NOT NULL,
  risk_level      TEXT NOT NULL CHECK (risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  slope_weight    REAL,
  wind_weight     REAL,
  model_version   TEXT
);

CREATE TABLE weather_obs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  mission_id    TEXT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
  observed_at   TEXT NOT NULL,
  wind_speed_kmh   REAL,
  wind_dir_deg     REAL,   -- FROM convention (meteorological)
  humidity_pct     REAL,
  temperature_c    REAL,
  source           TEXT DEFAULT 'open-meteo',
  is_cached        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE advisory (
  id               TEXT PRIMARY KEY,           -- ADV-20261114-01
  mission_id       TEXT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
  severity         TEXT NOT NULL CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  narrative        TEXT,
  action_ids_json  TEXT NOT NULL,              -- '["EVAC_IMMEDIATE",...]'
  model            TEXT NOT NULL,
  prompt_sha       TEXT NOT NULL,
  seed             INTEGER NOT NULL,
  dropped_ids      TEXT,
  error            TEXT,
  generated_at     TEXT NOT NULL
);

CREATE TABLE lora_packet (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  mission_id   TEXT REFERENCES mission(id) ON DELETE SET NULL,
  raw_hex      TEXT NOT NULL,
  lat          REAL,
  lon          REAL,
  altitude_m   INTEGER,
  fire_conf    INTEGER,
  smoke_conf   INTEGER,
  device_ts    INTEGER,
  received_at  TEXT NOT NULL,
  rssi_dbm     REAL,
  snr_db       REAL,
  crc_ok       INTEGER NOT NULL DEFAULT 1
);
```

**Design notes:**
* `severity` in the `advisory` table comes from the engine, not the model — consistent with §3.
* `action_ids_json` stores ids rather than text so wording can change without a data migration.
* `lora_packet.crc_ok` keeps packets rejected by hardware CRC for field diagnosis.

---

## 6. Heightmap Terrain Contract (Cesium)

Replaces the quantized-mesh tileset. One payload per mission.

```json
{
  "mission_id": "FLIGHT_20261114_001",
  "width": 256,
  "height": 256,
  "west": 107.6180,
  "south": -6.9185,
  "east": 107.6205,
  "north": -6.9160,
  "height_scale_m": 1.0,
  "geoid_offset_m": -1.42,
  "heights_m": [ 748.3, 748.9, 749.4, "... " ]
}
```

**Rules:**
* `heights_m` is a `width * height` array of floats in row-major order starting from the north-west corner.
* **`geoid_offset_m` is mandatory.** ODM produces heights above MSL (EGM96); `CustomHeightmapTerrainProvider` interprets heights above the ellipsoid. Without the offset, terrain shifts vertically by several metres and hotspot pins no longer sit on the surface.
* `height_scale_m` is for vertical exaggeration in the UI (default 1.0, never above 2.0 — pins become misleading).
* Downsample the DEM to 256×256 with `rasterio` (bilinear resampling). Over 100×100 m that is ~40 cm/pixel — enough for visualisation and still light.
* Masking (FR-DSH-05): the provider is bounded to `Rectangle(west, south, east, north)`. Outside it, Cesium does not render mission terrain.

---

## 7. Changelog

### 1.1.0
* **§1:** LoRa `lat`/`lon` `float32` → **`int32` scaled by $10^7$**. Precision rises from ~1.1 m to 1.1 cm with the same 16 bytes. Added endianness rules, hardware CRC, and rejection of timestamp `0`.
* **§2:** `spatial_fusion.json` gains `schema_version`, `mission_mode`, `photogrammetry`, `spread_prediction_alt`, `burn_scar`. Added the wind direction FROM vs TO warning.
* **§3:** advisory contract rewritten to follow the actual implementation — closed action catalog, `severity` from the engine, validation behaviour table, `audit` fields.
* **§4:** `.b3dm` endpoint removed; added `heightmap`, `mesh.glb`, `scar.geojson`, `/events` (SSE), `/lora/ingest`, `/health`. Added the SSE event shape.
* **§5:** SQLite schema (new).
* **§6:** Cesium heightmap contract (new), including the geoid offset.

### 1.0.0
* Initial version: LoRa `float32`, `spatial_fusion.json`, LLM prompt, four dashboard endpoints.
