# AGENTS.md — PyroScan Agentic Coding Guidelines

**Version:** 2.0.0
**Selaras dengan:** `product_requirement_document_pyroscan_prd.1.md` v1.3.1
**Status:** Aktif

> **Changelog 2.0.0** — NodeODM menggantikan WebODM (dengan keputusan eksplisit soal UI), LLM turun ke `qwen3.5:4b-q4_K_M` yang terukur, SQLite + FastAPI masuk stack, dua mode misi, Rust dinyatakan tidak dipakai, kontrak advisory dijadikan aturan kode. Lihat §12.

---

## 1. Project Context

PyroScan adalah sistem pemantauan, pemetaan, dan prediksi penyebaran kebakaran hutan terpadu.

Modul *extension* berbasis **smartphone Realme 3 Pro** (ditempel di perut drone) mengambil foto ber-geotag 12MP dan menjalankan deteksi api/asap on-device. Sepulang terbang, foto diproses di **Laptop Ground Station Lenovo LOQ (i7-HX + RTX 4060 8GB)** menjadi orthophoto, DEM, dan mesh 3D, lalu difusikan dengan data cuaca dan lereng untuk menghasilkan prediksi rambat api serta laporan naratif — semuanya **offline** — dan dirender di dashboard CesiumJS.

**Dua mode misi yang berbagi satu pipeline:**

| Mode | Input | Keluaran |
|---|---|---|
| **MODE-A** Pre-Fire Monitoring | Foto kanopi hidup + YOLO hotspot | Vektor prediksi rambat, tingkat risiko |
| **MODE-B** Burn-Scar Mapping | Foto permukaan hangus | Luas terbakar, batas api terakhir, relief |

Perbedaan keduanya hanya di lapisan metrik dan label UI. **Tidak ada dua aplikasi, tidak ada dua database.**

---

## 2. Hardware Baseline Context

1. **Airborne Payload:** Realme 3 Pro (Snapdragon 710, Adreno 616, Hexagon 685, 16MP Sony IMX519, Multi-GNSS). Camera2 level **harus diverifikasi** — kemungkinan `LEGACY`/`LIMITED`.
2. **Ground Station Server:** Lenovo LOQ (Intel i7-HX, **NVIDIA RTX 4060 Laptop 8 GB / 8188 MiB**, 16/32GB DDR5, Windows 11 / WSL2 Ubuntu).

**Batas VRAM efektif 7.2 GB.** Ini angka perencanaan, bukan 8.

---

## 3. System Architecture Overview

1. **Edge Payload (Realme 3 Pro):** Foreground service tipe `camera`, capture 12MP @2–4 s, EXIF GPS injection, TFLite YOLOv8n INT8 dengan *fallback chain*, log deteksi lokal. **Tanpa radio di Phase 1.**
2. **Server Posko (Lenovo LOQ):**
   * **Watcher** (`watchdog`) → baris `mission` di SQLite
   * **NodeODM** (Docker, CUDA) → `ortho.tif`, `dem.tif`, `mesh.glb`
   * **YOLOv8** (server-side verify) → daftar hotspot
   * **Mission Mode Resolver** → MODE-A / MODE-B
   * **Spatial Fusion** (`rasterio`) → `spatial_fusion.json`
   * **Spread Simulation** (`numpy`) → vektor prediksi (MODE-A)
   * **Burn Metrics** (`rasterio`) → luas/keliling (MODE-B)
   * **LLM Advisory Agent** (`qwen3.5:4b-q4_K_M` via Ollama) → advisory JSON, **serial dengan ODM**
3. **API Layer:** FastAPI + uvicorn, REST + SSE. Tanpa Redis, tanpa Celery.
4. **Frontend Dashboard:** React + Vite + Tailwind + CesiumJS. Termasuk **Photogrammetry Manager** yang menggantikan UI WebODM.

---

## 4. Photogrammetry Decision — NodeODM, bukan WebODM

**Keputusan: NodeODM.** WebODM tidak dipakai di jalur kritis.

| | WebODM | NodeODM |
|---|---|---|
| Peran | Aplikasi web: UI + DB project + orkestrasi | Mesin: REST API ke OpenDroneMap |
| Stack | Django + PostGIS + template HTML | Satu container Go/C++ |
| UI | Ada (template Django, bahasa Inggris, tidak bisa di-restyle) | Hampir tidak ada |
| Yang dipakai PyroScan | ~10% (trigger task, ambil hasil) | 100% kebutuhan |

**Konsekuensi yang diterima:** tidak ada UI manajemen photogrammetry bawaan. Penggantinya adalah **FR-DSH-07 Photogrammetry Manager** — satu halaman di dashboard PyroScan.

**Yang benar-benar hilang dan tidak diganti:** editor GCP / scale constraint. Jika DG-01 (SPIKE-01) menunjukkan kalibrasi GCP dibutuhkan, nyalakan WebODM sebagai **profil Docker opsional** yang menunjuk NodeODM yang sama — jangan jadikan dependensi jalur kritis.

**Aturan implementasi:**
* Semua panggilan ke NodeODM lewat satu modul klien (`server/photogrammetry/nodeodm.py`), tidak tersebar.
* Opsi ODM **wajib eksplisit** dan dikirim dari kode, bukan default container:
  `use-exif=true`, `gps-accuracy=15`, `resize-to=2000`, `feature-quality=medium`, `pc-quality=medium`, `orthophoto-resolution=2`.
* Progress dilaporkan lewat SSE dari polling `/task/{uuid}/info`, bukan WebSocket.
* `keep_alive` / lifecycle: NodeODM dan Ollama **tidak boleh** memegang GPU bersamaan (NFR-RELI-02).

---

## 5. Kontrak Advisory — Aturan Keras

Modul: `server/llm_agent/advisory.py`. Terverifikasi live.

Aturan ini **bukan preferensi gaya**, melainkan hasil pengukuran yang menemukan dua cacat nyata (lihat `llm_benchmark_pyroscan.md` §5).

1. **`severity` berasal dari simulation engine.** LLM tidak pernah ditanya dan tidak pernah boleh menimpanya. Model 4B terbukti menaikkan `HIGH` → `CRITICAL`.
2. **Aksi dipilih dari `ACTION_CATALOG` (id tertutup).** LLM mengembalikan `action_ids`, bukan teks bebas. Model terbukti mengarang "barikade air".
3. **Teks aksi dirender dari katalog**, bukan dari output model.
4. **Urutan aksi di-sort mengikuti prioritas katalog.** Evakuasi selalu di atas patroli.
5. **JSON tak terbaca → fallback 2 aksi prioritas tertinggi + flag `error`.** Advisory tidak boleh kosong.
6. **`risk_level` tak dikenal → `MEDIUM`.** Jangan pernah diam-diam turun ke `LOW`.
7. **Parameter Ollama wajib:** `num_ctx=8192`, `think=false`, `keep_alive=0`, `format=json`, `seed` tetap.
8. **Setiap advisory menyimpan audit:** `model`, `prompt_sha`, `seed`, `dropped_ids`.
9. **UI wajib memberi label "draf — verifikasi lapangan".** LLM bukan sumber keputusan SAR.

Menambah aksi baru = mengedit `ACTION_CATALOG` secara sadar. Jangan pernah melonggarkan validasi agar "model jadi lebih bebas".

---

## 6. Tech Stack & Conventions

| Lapisan | Teknologi | Catatan |
|---|---|---|
| Edge | Kotlin, Camera2, TFLite (INT8) | Fallback chain: NNAPI → GPU delegate FP16 → XNNPACK CPU |
| Pipeline | Python 3.12+, `watchdog`, `rasterio`, `numpy`, `ultralytics`, `requests` | Python 3.14 terbukti jalan di mesin ini |
| Photogrammetry | **NodeODM** (Docker, `--gpu`) | Bukan WebODM |
| LLM | **`qwen3.5:4b-q4_K_M`** via Ollama | 67.1 t/s, 11.4 s, 3.97 GB — terukur, bukan estimasi |
| Data | **SQLite** (`pyroscan.db`) | Tanpa Postgres, tanpa PostGIS |
| API | **FastAPI + uvicorn** | REST + SSE |
| Frontend | React + Vite + Tailwind + **CesiumJS** | Tanpa `resium`, tanpa Rust, tanpa Electron |

**`qwen3.5:9b` bukan default.** Ia kandidat yang belum terukur (unduhan gagal dua kali). Jangan menulis kode yang bergantung padanya.

---

## 7. Coding Rules for AI Agents

### 7.1. Batas Modul (keras)
* Jangan mencampur kode rendering CesiumJS dengan kalkulasi geospasial Python.
* Pisahkan tiga hal yang berbeda: **API server**, **pipeline photogrammetry**, **komponen UI**. Satu file tidak boleh menyentuh dua di antaranya.
* Modul klien eksternal (NodeODM, Ollama, Open-Meteo) masing-masing satu file, satu pintu.

### 7.2. Presisi Geospasial
* Koordinat desimal WGS84 (`lat`, `lon`), urutan konsisten di semua lapisan.
* File DEM **wajib** diproses lewat `rasterio`/GDAL. Jangan pernah mengubah matriks transform secara manual.
* Heightmap untuk Cesium butuh **offset geoid EGM96** (ODM menghasilkan tinggi di atas MSL, Cesium mengharapkan tinggi di atas ellipsoid). Simpan `geoid_offset_m` di payload dan terapkan di sisi Cesium.
* Timestamp dari GNSS, bukan jam laptop.

### 7.3. GPU
* RTX 4060 = index `0`. Set `CUDA_VISIBLE_DEVICES=0` dan NodeODM `--gpu`.
* **Serialisasi wajib:** ODM selesai → unload → LLM. `OLLAMA_KEEP_ALIVE=0`.
* Jika muncul OOM, periksa urutan, jangan langsung turunkan kualitas ODM.

### 7.4. Edge (Android)
* Inferensi TFLite **tidak boleh** mewajibkan `NnApiDelegate`. Ukur ketiga delegate di startup, pilih yang tercepat-stabil, catat di log.
* Foreground service tipe `camera`; layar mati saat capture.
* Default 12MP @2–4 s. Jangan naikkan resolusi untuk "kualitas" tanpa mengukur suhu.
* Log deteksi **lokal dan durabel** — data tidak boleh hilang kalau transfer gagal.

### 7.5. Frontend
* Warna: Obsidian `#070709`, Charcoal `#141419`, Silver `#9494a0`, Warm Amber `#e5a954`, aksen Flame Red/Orange.
* Cesium dimuat asinkron dan **di-mask ke area coverage misi** (FR-DSH-05). Tanpa mask, Cesium merender seluruh globe dan membuang FPS.
* Setiap state pipeline (menunggu, memproses, gagal, siap) harus punya tampilan. Fallback ke basemap 2D + pin jika DEM belum ada.

### 7.6. Error Handling & Offline
* Tidak ada panggilan jaringan ke internet di jalur kritis. Open-Meteo **wajib** punya cache offline terakhir beserta penanda usia data di UI.
* Komunikasi serial/socket butuh timeout + reconnect.
* Kegagalan LLM tidak boleh menggagalkan misi — advisory kosong dengan flag `error` lebih baik daripada pipeline berhenti.

---

## 8. File & Directory Structure

```
pyroscan/
├── Docs/
│   ├── product_requirement_document_pyroscan_prd.1.md
│   ├── hardware_specifications_pyroscan.md
│   ├── data_contracts_api_schema_pyroscan.md
│   ├── llm_benchmark_pyroscan.md
│   └── agents_guidelines_pyroscan.md
├── benchmarks/
│   ├── bench_llm.py                # harness stdlib-only, terukur
│   └── results/                    # hasil mentah per model
├── edge_payload/
│   ├── android_app/                # Kotlin: Camera2 + TFLite + foreground service
│   └── esp32_lora/                 # Phase 2. Kosong di Phase 1.
├── server/
│   ├── watchers/                   # watchdog → SQLite mission row
│   ├── photogrammetry/nodeodm.py   # satu-satunya pintu ke NodeODM
│   ├── ai_vision/                  # YOLOv8 inference + coordinate mapping
│   ├── simulation/                 # slope + wind spread model + burn metrics
│   ├── llm_agent/advisory.py       # ✅ sudah ada
│   ├── db.py                       # SQLite schema + query
│   └── api.py                      # FastAPI + SSE
├── frontend/
│   └── src/
│       ├── components/             # Map3D, AdvisoryPanel, WeatherWidget,
│       │                           # PhotogrammetryManager, MissionStatus
│       └── services/               # API client, SSE client
└── AGENTS.md                       # file ini
```

---

## 9. Verification Commands

Jangan mengklaim sesuatu bekerja tanpa menjalankan ini.

```powershell
# LLM advisory contract (10 assertion, offline)
python server\llm_agent\advisory.py

# dengan model nyata
python server\llm_agent\advisory.py --live qwen3.5:4b-q4_K_M

# benchmark LLM (jangan dijalankan bersamaan dengan ollama pull)
python benchmarks\bench_llm.py --repeats 3 qwen3.5:4b-q4_K_M

# GPU terpakai saat ODM berjalan
nvidia-smi --query-gpu=name,memory.used,utilization.gpu --format=csv
```

Baseline terukur yang harus tetap benar: **67.1 t/s decode, 11.4 s wall, 3.97 GB VRAM, JSON valid 3/3.**

---

## 10. Yang Tidak Boleh Dilakukan

| ❌ | Alasan |
|---|---|
| Memakai WebODM di jalur kritis | Django + PostGIS + UI yang tidak dipakai; satu titik gagal tambahan di lapangan |
| Memakai Rust di mana pun | Tidak ada SfM/MVS di Rust; Cesium adalah JS. UI bagus datang dari desain, bukan bahasa |
| Menambah Redis / Celery / Postgres | Satu operator, satu laptop. SQLite + asyncio cukup |
| Paralel NodeODM + LLM | 3.97 + 2–4 GB > 7.2 GB usable → OOM |
| Membiarkan LLM menentukan `severity` | Terbukti menaikkan `HIGH` → `CRITICAL` |
| Membiarkan LLM menulis teks aksi bebas | Terbukti mengarang "barikade air" |
| Memakai `resium` | Ketinggalan versi Cesium; pakai Cesium langsung dengan `useRef` |
| Memakai Cesium ion / CDN | Melanggar NFR-RELI-01 (offline) |
| Mengklaim FPS dari perasaan | Ukur p95 frame time |
| Menjanjikan akurasi EXIF absolut < 5 m | GNSS single-band sambil bergerak tidak bisa menjamin itu |

---

## 11. Prinsip Kerja

1. **Ukur sebelum menetapkan angka.** PRD v1.1.0 penuh angka yang tidak pernah diuji; v1.3.x menggantinya dengan hasil pengukuran. Jangan ulangi kesalahan itu.
2. **Risiko produk di atas risiko teknis.** Jika SfM di kanopi gagal (DG-01), tidak ada kode yang menyelamatkan. Uji itu lebih dulu.
3. **Satu bahasa per lapisan.** Python untuk pipeline, TypeScript untuk UI. Bahasa ketiga butuh justifikasi tertulis.
4. **Hapus sebelum menambah.** Setiap dependensi baru harus menggantikan sesuatu, bukan menumpuk.

---

## 12. Changelog

### 2.0.0
* **§4 ditambahkan:** keputusan NodeODM vs WebODM eksplisit, termasuk apa yang hilang (editor GCP) dan cara menutupnya.
* **§5 ditambahkan:** kontrak advisory sebagai aturan kode (severity dari engine, katalog aksi tertutup, fallback, audit).
* **Stack:** WebODM → NodeODM; `qwen3.5:9b` → `qwen3.5:4b-q4_K_M` (terukur); + SQLite, + FastAPI; Rust dinyatakan tidak dipakai.
* **§1:** dua mode misi.
* **§7.2:** offset geoid EGM96 untuk heightmap Cesium.
* **§9:** perintah verifikasi + baseline terukur.
* **§10:** daftar anti-pattern.
* **§8:** struktur direktori disesuaikan dengan file yang benar-benar ada.

### 1.0.0
* Versi awal.
