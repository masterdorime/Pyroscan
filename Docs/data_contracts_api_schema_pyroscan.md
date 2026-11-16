# API & Data Schema Specification — PyroScan

**Version:** 1.1.0
**Target:** Edge Payload, Server Pipeline, dan CesiumJS Dashboard
**Selaras dengan:** PRD v1.3.1, `server/llm_agent/advisory.py`

> **Changelog 1.1.0** — LoRa lat/lon `float32` → `int32` (presisi 1e-7, ukuran tetap 16 B); `spatial_fusion.json` dapat `schema_version` + `mission_mode` + `burn_scar`; kontrak advisory mengikuti katalog aksi tertutup; endpoint `.b3dm` dihapus; tambah skema SQLite dan kontrak heightmap. Lihat §7.

---

## 1. LoRa Binary Telemetry Payload (16-Byte Compact Struct)

Digunakan untuk transmisi radio jarak jauh dari ESP32 di drone ke Ground Station ketika sinyal seluler tidak tersedia. **Phase 2** — kontrak didefinisikan sekarang agar firmware dan parser tidak perlu diubah dua kali.

### 1.1. Byte Structure Layout

| Byte Offset | Variable | Type | Skala / Unit | Description |
|---|---|---|---|---|
| `0..3` | `lat_e7` | `Int32` | derajat $\times 10^{7}$ | Latitude WGS84 |
| `4..7` | `lon_e7` | `Int32` | derajat $\times 10^{7}$ | Longitude WGS84 |
| `8..9` | `altitude` | `Int16` | meter | Ketinggian relatif dari take-off |
| `10` | `fire_conf` | `UInt8` | $0 - 100$ | Confidence deteksi api (%) |
| `11` | `smoke_conf` | `UInt8` | $0 - 100$ | Confidence deteksi asap (%) |
| `12..15` | `timestamp` | `UInt32` | UNIX epoch (s) | Waktu capture dari GNSS |

**Total: 16 byte.** Tidak berubah dari v1.0.0.

### 1.2. Mengapa `int32`, bukan `float32`

`float32` hanya memberi ~7 digit signifikan. Pada lat -6,9175 (2 digit di depan koma), sisa presisi jatuh ke ~1,1 m *terbaik* dan memburuk seiring besarnya nilai. `int32` dengan skala $10^{7}$ memberi **1,1 cm** dan eksak — tanpa menambah satu byte pun.

Rentang aman: lat $\pm 900{,}000{,}000$ dan lon $\pm 1{,}800{,}000{,}000$, keduanya di dalam `int32` ($\pm 2{,}147{,}483{,}647$).

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

### 1.4. Aturan Wire Format

* **Endianness: little-endian**, eksplisit di kedua sisi. Jangan mengandalkan `__BYTE_ORDER__` host — dokumentasikan sebagai LE dan konversi bila perlu.
* **Tidak ada CRC aplikasi.** SX1262 punya CRC hardware; aktifkan (`radio.setCRC(true)`) dan andalkan paket dengan CRC gagal dibuang di radio.
* Timestamp berasal dari GNSS, bukan jam HP. Paket dengan timestamp `0` harus ditolak receiver.
* Parser menerima pula `RSSI` dan `SNR` dari radio, lalu menyimpannya di tabel `lora_packet` (§5).

---

## 2. Server Spatial Data Fusion Schema (`spatial_fusion.json`)

Format pertukaran internal server posko setelah photogrammetry, YOLO, dan cuaca selesai. Ini **satu-satunya** input untuk simulation engine dan LLM advisory.

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
      "description": "Horizon utama (30-60 menit). Hanya untuk MODE-A.",
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
      "description": "Horizon tambahan. Sama bentuknya dengan spread_prediction.",
      "items": { "type": "object" }
    },
    "burn_scar": {
      "type": "object",
      "description": "Hanya untuk MODE-B.",
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
      "description": "wind_direction_deg adalah arah DARI mana angin bertiup (meteorologis). 225 = angin dari barat daya, api merambat ke timur laut."
    }
  }
}
```

> **Jebakan yang harus dihindari:** `wind_direction_deg` memakai konvensi **FROM** (meteorologis). Vektor rambat api = arah **TO** = `wind_direction_deg + 180`. Salah tanda di sini membalik seluruh prediksi.

---

## 3. Local LLM Advisory Contract

Implementasi acuan: `server/llm_agent/advisory.py`. Kontrak ini **dipaksakan oleh kode**, bukan oleh prompt.

### 3.1. Input: hanya subset `spatial_fusion.json`

LLM menerima angka, **bukan** `risk_level` sebagai instruksi. `severity` dihitung di luar model.

### 3.2. Katalog aksi tertutup

| ID | Teks yang dirender ke UI |
|---|---|
| `EVAC_IMMEDIATE` | Evakuasi segera warga pada sektor yang dilalui arah rambat api. |
| `EVAC_ROUTE` | Aktifkan rute evakuasi alternatif yang menjauhi arah rambat, bukan mengikuti arah angin. |
| `FIREBREAK` | Bangun firebreak/sekat bakar pada kontur yang ditentukan di depan lidah api. |
| `AERIAL` | Ajukan pemadaman udara (water bombing) pada koordinat prediksi. |
| `PATROL` | Tingkatkan patroli dan pemantauan hotspot di sepanjang jalur prediksi. |
| `EARLY_WARNING` | Aktifkan peringatan dini dan koordinasi lintas instansi. |

Model hanya mengembalikan `action_ids`. Teks dirender dari tabel ini di server.

### 3.3. Request ke Ollama

```json
{
  "model": "qwen3.5:4b-q4_K_M",
  "prompt": "<lihat build_prompt()>",
  "stream": false,
  "format": "json",
  "think": false,
  "keep_alive": 0,
  "options": { "num_ctx": 8192, "temperature": 0.2, "seed": 42 }
}
```

### 3.4. Response yang diharapkan dari model (tidak dipercaya mentah)

```json
{
  "summary_narrative": "Api bergerak cepat ke timur laut ...",
  "action_ids": ["EVAC_IMMEDIATE", "FIREBREAK", "AERIAL", "PATROL"]
}
```

`severity` dan `action_items` **tidak** diminta ke model. Jika model tetap mengirimnya, nilainya dibuang.

### 3.5. Advisory final (yang disimpan dan dikirim ke UI)

```json
{
  "severity": "HIGH",
  "summary_narrative": "Api bergerak cepat menuju titik -6.912, 107.625 dalam 45 menit ...",
  "action_items": [
    "Evakuasi segera warga pada sektor yang dilalui arah rambat api.",
    "Bangun firebreak/sekat bakar pada kontur yang ditentukan di depan lidah api.",
    "Ajukan pemadaman udara (water bombing) pada koordinat prediksi.",
    "Tingkatkan patroli dan pemantauan hotspot di sepanjang jalur prediksi."
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

**Aturan validasi (implemented):**

| Kondisi | Perilaku |
|---|---|
| `severity` dari model ≠ engine | Diabaikan; pakai engine |
| `risk_level` engine di luar enum | → `MEDIUM` |
| `action_ids` berisi id tak dikenal | Masuk `dropped_ids`, tidak ditampilkan |
| `action_ids` kosong setelah filter | Fallback 2 id prioritas tertinggi |
| Urutan `action_ids` dari model | Di-sort ulang mengikuti urutan katalog |
| JSON tidak bisa di-parse | `error: "unparseable_json"`, advisory tetap berisi aksi fallback |
| `summary_narrative` kosong/bukan string | String kosong, `error` tidak diubah |

---

## 4. REST API (FastAPI)

Base: `http://<posko-lan>:8000/api/v1`

| Method | Endpoint | Deskripsi | Response |
|---|---|---|---|
| `GET` | `/health` | Status server, DB, GPU, Ollama | JSON |
| `GET` | `/missions` | Daftar misi (paginated) | `Mission[]` |
| `POST` | `/missions` | Buat misi dari folder foto | `Mission` |
| `GET` | `/missions/{id}` | Detail misi + status pipeline | `Mission` |
| `GET` | `/missions/latest` | Misi terakhir & telemetri | `Mission` |
| `GET` | `/missions/{id}/fusion` | `spatial_fusion.json` | JSON (§2) |
| `GET` | `/missions/{id}/advisory` | Advisory terakhir | JSON (§3.5) |
| `POST` | `/missions/{id}/advisory` | Regenerate advisory | JSON (§3.5) |
| `GET` | `/missions/{id}/heightmap` | Heightmap terrain untuk Cesium | JSON (§6) |
| `GET` | `/missions/{id}/ortho.tif` | Orthophoto GeoTIFF | `image/tiff` |
| `GET` | `/missions/{id}/mesh.glb` | Mesh 3D bertekstur | `model/gltf-binary` |
| `GET` | `/missions/{id}/scar.geojson` | Polygon burn scar (MODE-B) | `application/geo+json` |
| `GET` | `/events` | **SSE**: progres misi | `text/event-stream` |
| `POST` | `/lora/ingest` | Terima paket dari receiver serial | JSON |

**Dihapus dari v1.0.0:** `GET /tiles/3d/{z}/{x}/{y}.b3dm`. ODM tidak menghasilkan 3D Tiles; konversinya butuh Cesium ion atau toolchain tambahan yang bertentangan dengan NFR-RELI-01. Mesh dilayani sebagai satu `.glb` utuh lalu diposisikan di Cesium via `Model.fromGltfAsync`.

### 4.1. SSE event shape

```
event: mission_update
data: {"mission_id":"FLIGHT_20261114_001","stage":"PHOTOGRAMMETRY","progress":0.62,"message":"Matching 30 images"}

event: mission_update
data: {"mission_id":"FLIGHT_20261114_001","stage":"DONE","progress":1.0,"advisory_id":"ADV-20261114-01"}
```

Tahapan (`stage`): `CAPTURING` → `PHOTOGRAMMETRY` → `FUSION` → `SIMULATION` → `ADVISORY` → `DONE` | `FAILED`.

---

## 5. SQLite Schema (`pyroscan.db`)

Tanpa Postgres, tanpa PostGIS. Semua timestamp ISO-8601 UTC.

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
  wind_dir_deg     REAL,   -- konvensi FROM (meteorologis)
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

**Catatan desain:**
* `severity` di tabel `advisory` berasal dari engine, bukan model — konsisten dengan §3.
* `action_ids_json` disimpan sebagai id, bukan teks, agar wording bisa diubah tanpa migrasi data.
* `lora_packet.crc_ok` menyimpan paket yang ditolak hardware CRC untuk diagnosis lapangan.

---

## 6. Heightmap Terrain Contract (Cesium)

Pengganti tileset quantized-mesh. Satu payload per misi.

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
  "heights_m": [ 748.3, 748.9, 749.4, "..." ]
}
```

**Aturan:**
* `heights_m` = array `width * height` nilai float, urut baris-mayor dari barat laut.
* **`geoid_offset_m` wajib diisi.** ODM menghasilkan tinggi di atas MSL (EGM96); `CustomHeightmapTerrainProvider` menginterpretasikan tinggi di atas ellipsoid. Tanpa offset, terrain akan tampak bergeser vertikal beberapa meter dan pin hotspot tidak menempel di permukaan.
* `height_scale_m` untuk eksagerasi vertikal di UI (default 1.0, jangan > 2.0 — pin jadi menyesatkan).
* Downsample DEM ke 256×256 lewat `rasterio` (resampling bilinear). Untuk area 100×100 m itu ~40 cm/piksel, cukup untuk visualisasi dan tetap ringan.
* Masking (FR-DSH-05): provider dibatasi ke `Rectangle(west, south, east, north)`. Di luar itu Cesium tidak merender terrain misi.

---

## 7. Changelog

### 1.1.0
* **§1:** LoRa `lat`/`lon` `float32` → **`int32` skala $10^7`**. Presisi naik dari ~1,1 m ke 1,1 cm, ukuran tetap 16 byte. Tambah aturan endianness, CRC hardware, dan penolakan timestamp `0`.
* **§2:** `spatial_fusion.json` dapat `schema_version`, `mission_mode`, `photogrammetry`, `spread_prediction_alt`, `burn_scar`. Tambah peringatan konvensi arah angin FROM vs TO.
* **§3:** kontrak advisory ditulis ulang mengikuti implementasi nyata — katalog aksi tertutup, `severity` dari engine, tabel perilaku validasi, field `audit`.
* **§4:** endpoint `.b3dm` dihapus; tambah `heightmap`, `mesh.glb`, `scar.geojson`, `/events` (SSE), `/lora/ingest`, `/health`. Tambah bentuk event SSE.
* **§5:** skema SQLite (baru).
* **§6:** kontrak heightmap Cesium (baru), termasuk offset geoid.

### 1.0.0
* Versi awal: LoRa `float32`, `spatial_fusion.json`, prompt LLM, empat endpoint dashboard.
