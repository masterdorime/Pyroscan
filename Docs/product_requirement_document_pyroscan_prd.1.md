# Product Requirement Document (PRD) — PyroScan

**Version:** 1.3.1
**Status:** Approved / In Development
**Author:** Tristan Edgina Rakhadewa
**Target Delivery:** MVP Phase

> **Changelog 1.3.1** — Benchmark LLM nyata di RTX 4060 Laptop; default jadi `qwen3.5:4b-q4_K_M`; `severity` dikeluarkan dari LLM. Lihat §10.

---

## 1. Executive Summary & Objective

**PyroScan** adalah sistem pemantauan, pemetaan 3D, dan prediksi perambatan kebakaran hutan berbasis *edge AI*, *photogrammetry*, dan *LLM Advisory Agent*.

Sistem ini memanfaatkan *extension payload* berupa **smartphone Android bekas (Realme 3 Pro)** yang ditempelkan di bawah perut drone (*belly mount*) untuk mengambil foto ber-geotag (EXIF GPS) dan mendeteksi titik api/asap di udara. Begitu mendarat, foto disinkronkan ke **Laptop Posko Darat (Lenovo LOQ RTX 4060 i7-HX)** untuk diolah menjadi peta medan 3D (*Orthomosaic & DEM*), digabungkan dengan data cuaca serta analisis kemiringan lereng untuk mendeteksi *hotspot* dan memprediksi pergerakan api 30–60 menit ke depan, lalu disajikan sebagai *dashboard* interaktif **CesiumJS** dan laporan naratif **Qwen3.5-9B**.

### 1.1. Dua Mode Misi

PyroScan mendukung **dua mode operasi** sejak MVP. Keduanya memakai payload, pipeline, dan dashboard yang sama — yang berbeda hanya interpretasi hasil dan cara prediksi dihitung.

| Mode | Kapan dipakai | Sumber data | Yang dihasilkan |
|---|---|---|---|
| **MODE-A: Pre-Fire Monitoring** | Sebelum / di depan api, area belum terbakar | Foto kanopi hidup + YOLO hotspot + DEM | Peta bahan bakar, lereng, vektor prediksi arah rambat |
| **MODE-B: Burn-Scar Mapping** | Pasca-kebakaran | Foto permukaan hangus + DEM | Luas terbakar, batas api terakhir, topografi bekas bakar |

**Alasan teknis mode ganda:** kanopi hutan hidup adalah subjek terburuk untuk *feature matching* SfM (tekstur berulang, homogen, bergerak tertiup angin). Permukaan hangus justru kaya tekstur dan statis. Dengan mendukung MODE-B, proyek tetap punya jalur sukses yang terjamin meski MODE-A gagal di lapangan — dan MODE-B justru memberi angka validasi (luas terbakar) yang berguna untuk MODE-A berikutnya.

### 1.2. Prinsip Desain

1. **Satu container photogrammetry, tanpa web app.** Pipeline memakai **NodeODM** langsung via REST. WebODM (Django + PostGIS + UI bawaan) tidak dipakai; UI manajemen dibuat sendiri di dashboard agar konsisten secara visual.
2. **LLM terukur, bukan diasumsikan.** `qwen3.5:4b-q4_K_M` terukur 67 t/s / 11.4 s / 3.97 GB dan lolos KPI latency 7.9×. Model 9B hanya dipertimbangkan jika terbukti lebih baik secara narasi. Mode *thinking* dimatikan. `severity` tidak pernah diproduksi LLM (§5.2 FR-SRV-06a).
3. **Terrain secukupnya.** Area misi 100×100 m dirender dengan heightmap lokal via `CustomHeightmapTerrainProvider`, bukan tileset quantized-mesh.
4. **Serialisasi GPU.** Photogrammetry dan LLM **tidak boleh** berjalan bersamaan pada 8 GB VRAM.
5. **Tidak ada bahasa kedua.** Python untuk pipeline, TypeScript untuk UI. Tidak ada Rust, tidak ada service tambahan.

---

## 2. Hardware Baseline Specifications

### 2.1. Edge Payload Module (Airborne)
* **Device:** Realme 3 Pro (Custom Enclosure 3D Print PETG + Rubber Damper).
* **SoC / Compute:** Qualcomm Snapdragon 710 (10nm), GPU Adreno 616, Hexagon 685 DSP.
* **Camera Sensor:** 16MP Sony IMX519 ($f/1.7$, EXIF Geotagging via Multi-GNSS GPS/GLONASS/Galileo).
* **Connectivity:** Wi-Fi lokal (Phase 1). USB-C OTG Serial ke ESP32 LoRa Transmitter (Phase 2).
* **Camera2 Level:** **Wajib diverifikasi** (`INFO_SUPPORTED_HARDWARE_LEVEL`). Realme 3 Pro pada Android 9/10 kemungkinan hanya `LEGACY`/`LIMITED`, sehingga kontrol exposure manual dan frame rate mungkin terbatas. Lihat `hardware_specifications_pyroscan.md` §8.

### 2.2. Ground Station Server (Ground Posko)
* **Device:** Laptop Lenovo LOQ Series.
* **CPU:** Intel Core i7 HX-series (High Performance Multi-core).
* **GPU:** NVIDIA GeForce RTX 4060 8GB GDDR6 (CUDA Enabled) — *laptop SKU, bus 128-bit (~256 GB/s), 80–115 W, thermal throttling expected*.
* **RAM:** 16GB / 32GB DDR5.
* **OS Environment:** Windows 11 / Ubuntu Linux via WSL2, Docker Desktop, Ollama Runtime.

### 2.3. VRAM Budget (8 GB — hard constraint)

Diukur pada hardware aktual (RTX 4060 Laptop 8188 MiB). Lihat `llm_benchmark_pyroscan.md`.

| Komponen | VRAM | Sumber | Aktif bersamaan? |
|---|---|---|---|
| NodeODM / OpenSfM feature extraction | ~2–4 GB | estimasi | ❌ serial |
| `qwen3.5:4b-q4_K_M` @ `num_ctx=8192` | **3.97 GB** | **terukur** | ❌ serial |
| `qwen3.5:9b` Q4_K_M @ `num_ctx=8192` | ~5.9 GB | estimasi | ❌ serial |
| `gemma4:e4b` @ `num_ctx=8192` | 4.41 GB | terukur | ❌ serial |

**Aturan:** pipeline **wajib** menjalankan photogrammetry dan LLM secara berurutan. `OLLAMA_KEEP_ALIVE=0` diset agar model tidak menahan VRAM setelah generasi selesai. VRAM efektif yang dapat dipakai ~7.2 GB (bukan 8), sehingga 3.97 + 2–4 GB hanya muat jika serial.

---

## 3. Target User & Use Cases

### Target User
1. **Komandan Posko Bencana / Tim SAR:** Membutuhkan keputusan cepat mengenai rute evakuasi dan titik pemutusan vegetasi (*firebreak*).
2. **Operator Drone Lapangan:** Membutuhkan modul *payload* ringkas yang otomatis mengambil data tanpa mengganggu fungsi penerbangan drone.

### Key Use Cases
* **UC-00 (Pre-Flight Verification):** Operator memverifikasi kamera, GNSS fix, dan thermal state sebelum lepas landas lewat halaman *pre-flight check* di dashboard.
* **UC-01 (Post-Flight 3D Mapping):** Menyalin foto secara *bulk* via Wi-Fi lokal posko ke Lenovo LOQ, lalu memprosesnya GPU CUDA **NodeODM** menjadi model medan 3D, orthophoto, dan DEM.
* **UC-02 (Burn-Scar Quantification — MODE-B):** Dari foto area terbakar, menghitung luas terbakar, batas api terakhir, dan relief pasca-bakar.
* **UC-03 (Fire Spread Simulation — MODE-A):** Menghitung vektor kecepatan & arah api berdasarkan kombinasi sudut kelandaian lereng (*slope*) dan angin.
* **UC-04 (Offline LLM Executive Advisory):** Menghasilkan laporan naratif otomatis menggunakan `qwen3.5:9b` (lokal di VRAM RTX 4060) tentang tingkat risiko dan rekomendasi tindakan SAR.
* **UC-05 (In-Flight Alerting — Phase 2):** Mengirim indikator *hotspot* dan koordinat GPS via LoRa (16-byte payload) saat AI di Realme 3 Pro mendeteksi api. *Kontrak data tetap didefinisikan; implementasi ditunda (§9 DG-02).*

---

## 4. System Architecture & Data Flow

```
[ Drone Payload: Realme 3 Pro (Snapdragon 710) ]
   ├── Camera2 12MP default (16MP max) ──> Auto-Geotagged EXIF Photos
   ├── On-Device TFLite ──> hotspot log (on-device, Phase 1)
   ├── [Phase 2] LoRa 16-byte alert via ESP32/SX1262
   └── Foreground Service (camera type) + local storage
            │
            ▼ (Bulk Transfer Post-Landing via Wi-Fi ke router posko)
[ Ground Station Server: Lenovo LOQ (i7-HX + RTX 4060 8GB) ]
   ├── Directory Watcher (watchdog)   ──> SQLite mission row
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
   ├── CustomHeightmapTerrainProvider (DEM lokal)
   ├── SingleTileImageryProvider (orthophoto lokal)
   ├── Hotspot pins + prediction vector arrows
   ├── Burn-scar polygon overlay  [MODE-B]
   └── Advisory Panel + Weather Widget
```

---

## 5. Functional Requirements

### 5.1. Edge Payload Module (Android App on Realme 3 Pro)
* **FR-PAY-01:** Aplikasi Android berjalan sebagai **foreground service** tipe `camera` yang mengambil foto pada interval terkonfigurasi ($2–4\text{ detik}$ default). Resolusi default **12MP**, maksimum 16MP.
* **FR-PAY-02:** Aplikasi otomatis menyuntikkan koordinat GPS ($Lat, Lon, Alt$) dan timestamp GNSS ke metadata EXIF setiap citra JPEG.
* **FR-PAY-03 (Delegate Fallback Chain):** Menjalankan inferensi **YOLOv8n TFLite (INT8)** dengan rantai fallback yang **diukur, bukan diasumsikan**: `NNAPI` → `GPU delegate (FP16)` → `XNNPACK CPU (INT8)`. Delegate tercepat yang stabil saat startup dipilih dan dicatat di log. **NNAPI tidak wajib berhasil** — pada Snapdragon 710 NNAPI sering memecah graph dan lebih lambat dari XNNPACK.
* **FR-PAY-04:** Menyimpan seluruh hasil deteksi ke log lokal (CSV/JSON) beserta timestamp, agar tidak ada data hilang bila transfer gagal.
* **FR-PAY-05 (SOP Operator):** Karena ColorOS membunuh background service secara agresif, aplikasi wajib menyediakan layar onboarding yang memandu: izin kamera + lokasi background, pengecualian battery optimization, dan izin autostart.
* **FR-PAY-06 (Phase 2):** Mengirim telemetri 16-byte via USB-C OTG ke ESP32 LoRa transmitter. Kontrak data di `data_contracts_api_schema_pyroscan.md` §1.

### 5.2. Ground Station Server Pipeline (Lenovo LOQ RTX 4060)
* **FR-SRV-01 (Directory Watcher):** Mendeteksi berkas foto baru (`watchdog`) dan membuat/melanjutkan baris `mission` di SQLite.
* **FR-SRV-02 (CUDA Photogrammetry — NodeODM):** Memicu **NodeODM** (single container, REST API) dengan opsi eksplisit: `use-exif: true`, `gps-accuracy: 15`, `resize-to: 2000`, `feature-quality: medium`, `pc-quality: medium`, `orthophoto-resolution: 2`. Output: `odm_orthophoto.tif`, `odm_dem.tif`, `odm_textured_model_geo.glb`.
* **FR-SRV-03 (Spatial Fusion Engine):** Membaca elevasi/kelandaian/aspect dari DEM `.tif` via `rasterio` pada koordinat hotspot. Menyusun `spatial_fusion.json`.
* **FR-SRV-04 (Fire Spread Simulation — MODE-A):** Menghitung proyeksi posisi api 30–60 menit ke depan dari vektor angin (Open-Meteo dengan cache offline terakhir) dan dorongan lereng (*Rothermel-inspired slope factor*). Parameter `slope_weight` / `wind_weight` **wajib konfigurabel** (kalibrasi Phase 3).
* **FR-SRV-05 (Burn Metrics — MODE-B):** Menghitung luas terbakar, keliling, dan bounding box dari klasifikasi permukaan hangus pada orthophoto. Output dipakai sebagai lapisan polygon di dashboard dan sebagai ground-truth untuk kalibrasi MODE-A.
* **FR-SRV-06 (Local LLM Copilot):** Mengirim konteks JSON spasial ke model via Ollama API lokal, meminta output JSON terstruktur. Parameter wajib: `num_ctx=8192`, `think: false`, `OLLAMA_KEEP_ALIVE=0` (semua **terbukti terukur**, lihat `llm_benchmark_pyroscan.md`). Berjalan **setelah** photogrammetry selesai.
  * **FR-SRV-06a:** `severity` **tidak boleh** dihasilkan oleh LLM. Nilai itu berasal dari simulation engine yang deterministik dan diteruskan apa adanya. LLM hanya mengisi `summary_narrative` dan `action_items`. Alasan: pada benchmark, `qwen3.5:4b` menaikkan `HIGH` (dari mesin) menjadi `CRITICAL` — dua misi dengan data identik bisa memberi tingkat ancaman berbeda.
  * **FR-SRV-06b:** `action_items` divalidasi pasca-generasi terhadap kosakata tindakan yang diizinkan (evakuasi, firebreak, rute, koordinasi). Item di luar daftar dibuang, bukan ditampilkan.
  * **FR-SRV-06c:** Setiap advisory disimpan dengan `model`, `prompt_sha`, dan `seed` untuk audit, dan ditampilkan di dashboard dengan label **"draf — verifikasi lapangan"**.
* **FR-SRV-07 (Persistence):** Seluruh state misi, hotspot, prediksi, observasi cuaca, dan advisory disimpan di **SQLite** (`pyroscan.db`).
* **FR-SRV-08 (API Layer):** **FastAPI + uvicorn** pada LAN posko menyajikan REST + SSE untuk progres misi. Tanpa Redis, tanpa Celery.

### 5.3. Dashboard Admin (Frontend)
* **FR-DSH-01:** Merender medan 3D menggunakan **CesiumJS** dengan `CustomHeightmapTerrainProvider` yang dibangun dari `odm_dem.tif`. Tidak memakai tileset quantized-mesh, tidak memakai Cesium ion.
* **FR-DSH-02:** Menancapkan *pinpoint* 3D interaktif untuk **Api Aktif** (Pin Merah) dan **Prediksi 1 Jam Ke Depan** (Pin Oranye) beserta garis panah vektor perambatan.
* **FR-DSH-03:** Menampilkan *Advisory Panel* berisi laporan naratif hasil `qwen3.5:9b`.
* **FR-DSH-04:** Menyediakan *Weather Widget* (kecepatan angin, arah angin, suhu, kelembapan) beserta penanda usia data.
* **FR-DSH-05 (Masking & Culling):** Orthophoto dan mesh Cesium wajib di-*mask* ke area coverage misi. Tanpa ini, Cesium merender seluruh globe dan membuang performa pada area di luar 100×100 m.
* **FR-DSH-06 (Fallback):** Jika DEM/mesh belum siap, dashboard menampilkan basemap 2D + pin hotspot + banner status pipeline.
* **FR-DSH-07 (Photogrammetry Manager):** Satu halaman untuk memilih folder foto, memulai task ODM, memantau progres via SSE, dan mem-preview hasil (orthophoto, DEM, mesh, jumlah foto ter-align). Menggantikan UI bawaan WebODM.

---

## 6. Non-Functional Requirements

* **NFR-PERF-01 (Payload Weight):** Total bobot modul *extension* (Realme 3 Pro tanpa backcover + *casing* 3D print + ESP32 + antena + damper) tidak boleh melebihi **190 gram**. Rincian di `hardware_specifications_pyroscan.md` §6.
* **NFR-PERF-02 (Processing Time):** Dengan `resize-to: 2000` dan `feature-quality: medium`, pemrosesan **30 foto @12MP area 100×100 m** dari mendarat hingga render 3D harus selesai **< 4 menit**. Angka ini **harus divalidasi pada hardware nyata** sebelum dijadikan komitmen; dataset 50 foto @16MP dengan kualitas default diperkirakan jauh melebihi target.
* **NFR-RELI-01 (Offline Operation):** Server posko dan *dashboard* beroperasi **100% offline** — NodeODM lokal, Ollama lokal, terrain & orthophoto dari berkas lokal. Tidak ada dependensi ke Cesium ion, CDN, atau tile server publik.
* **NFR-RELI-02 (GPU Serialization):** Pipeline wajib menjamin photogrammetry dan LLM tidak menempati VRAM secara bersamaan. Pelanggaran ini menghasilkan OOM, bukan degradasi performa.
* **NFR-SEC-01 (Data Integrity):** Data GPS dan *flight log* disimpan paralel di memori internal HP dan SSD laptop posko untuk mencegah kehilangan data jika drone mengalami musibah (*crash*).
* **NFR-COST-01 (Zero Recurring Cost):** Tidak ada layanan berbayar (cloud compute, tile hosting, LLM API) dalam alur operasional.
* **NFR-MAINT-01 (Two Languages Only):** Python untuk pipeline, TypeScript untuk UI. Tidak ada service, runtime, atau bahasa tambahan di jalur kritis.

---

## 7. Success Metrics (KPI)

Hanya metrik yang punya **prosedur ukur jelas** dan **data source yang benar-benar ada** dipertahankan. Metrik aspirasional tanpa metode validasi dihapus (lihat §10).

| Indikator (KPI) | Prosedur Ukur | Target Minimum (MVP) |
|---|---|---|
| **YOLOv8 deteksi api/asap** | mAP50 terhadap validation set lapangan yang di-*hold out* | $> 80\%$ |
| **Foto ter-align (SfM success rate)** | `num_reconstructed` ÷ `num_images` dari report NodeODM | $> 80\%$ MODE-B, $> 60\%$ MODE-A |
| **Waktu processing end-to-end** | `time` dari watcher trigger → semua artefak tersedia di SQLite | $< 4\text{ menit}$ (30 foto @12MP) |
| **Akurasi relatif orthophoto** | RMSE antar ≥ 3 checkpoint GCP darat | $< 2\text{ m}$ |
| **Error posisi hotspot** | Jarak pin vs posisi api ground-truth yang diukur manual | $< 15\text{ m}$ |
| **Frame time dashboard** | p95 frame time @ 1080p, Cesium render loop, 60 detik sampling | $< 33\text{ ms}$ |
| **Latency advisory** | Dari status ODM `DONE` → advisory JSON tersimpan | $< 90\text{ s}$ (**terukur 11.4 s**) |

> **Dihapus dari v1.1.0:** "60 FPS" (bukan metrik tunggal — diganti p95 frame time), "EXIF accuracy < 5 m" (tidak dapat dijamin dari GNSS single-band sambil bergerak — diganti akurasi relatif + error hotspot), "LLM > 15 tokens/detik" (bukan indikator keberhasilan produk; tetap diukur di benchmark tapi bukan KPI).

---

## 8. Phased Roadmap

### Phase 0: Technical Spike (Gate — kerjakan sebelum kode produksi)
* **SPIKE-01 (Blocking / DG-01):** Ambil 20–30 foto nadir dari HP pada ketinggian operasional di atas **kanopi hutan hidup**. Jalankan photogrammetry. Ukur: persentase foto ter-align, RMSE reprojection, waktu proses.
  * Jika gagal ≥ 60% align → MODE-A tidak layak, produk bergerak ke MODE-B sebagai mode utama. **Keputusan diambil sebelum Phase 1 menulis kode pipeline.**
* **SPIKE-02:** Verifikasi `INFO_SUPPORTED_HARDWARE_LEVEL`, kontrol exposure Camera2, dan rolling shutter pada Realme 3 Pro.
* **SPIKE-03:** Benchmark tiga delegate TFLite pada perangkat; catat FPS dan suhu setelah 10 menit capture kontinu.
* **SPIKE-04:** Benchmark `qwen3.5:9b` vs `qwen3-vl:4b` di laptop: tok/s, VRAM peak, kualitas bahasa Indonesia. Simpan hasilnya di dokumen ini sebagai tabel terukur.
* **SPIKE-05:** Pastikan dataset YOLO fire/smoke tersedia dan lisensinya sesuai penggunaan (Ultralytics = AGPL-3.0).
* **SPIKE-06:** Verifikasi regulasi frekuensi LoRa Indonesia (DG-02) — hanya jika LoRa diaktifkan di Phase 2.

### Phase 1: MVP Core (Current Focus)
* Aplikasi Android capture EXIF GPS foreground service pada Realme 3 Pro.
* Pipeline Python: `watchdog` + NodeODM Docker CUDA + YOLOv8 + fusion + spread simulation + burn metrics.
* SQLite + FastAPI (REST + SSE).
* Dashboard React + CesiumJS: heightmap terrain, hotspot pins, prediction arrows, burn-scar polygon, advisory panel.
* Photogrammetry Manager (FR-DSH-07) sebagai pengganti UI WebODM.
* Training/evaluasi model YOLOv8n fire & smoke (workstream eksplisit).
* Validasi KPI §7 pada hardware nyata; revisi angka bila meleset.

### Phase 2: Hardware Integration & LoRa
* Integrasi serial USB OTG Realme 3 Pro → ESP32 LoRa (SX1262) + receiver di posko. **Hanya jika DG-02 lulus dan drone terbukti tidak punya telemetry link sendiri.**
* Pembuatan *3D Printed Enclosure* final +verifikasi bobot dan damper.

### Phase 3: Field Testing & Calibration
* Uji coba lapangan dengan penerbangan drone nyata (MODE-A dan MODE-B).
* Kalibrasi ulang `slope_weight` vs `wind_weight` pada rumus vektor perambatan api, memakai luas burn-scar MODE-B sebagai pembanding.
* Kalibrasi `gps-accuracy` dan penempatan GCP.

---

## 9. Risk Register & Decision Gates

| # | Risiko | Dampak | Status | Mitigasi |
|---|---|---|---|---|
| R-01 | **SfM gagal di atas kanopi hutan hidup** | Fatal untuk MODE-A | **DG-01, blocking** | SPIKE-01. Jika gagal, MODE-B jadi mode utama dan MODE-A jadi fitur eksperimental yang ditandai jelas di UI. |
| R-02 | **Target waktu processing tidak tercapai** | Tinggi | Terbuka | Turunkan resolusi/quality ODM, ukur nyata, revisi NFR-PERF-02 sebelum dijanjikan. |
| R-03 | **VRAM 8 GB tidak cukup saat ODM + LLM** | Tinggi | Mitigated NFR-RELI-02 | Serialisasi pipeline, `OLLAMA_KEEP_ALIVE=0`, model 9B Q4. |
| R-04 | **ColorOS membunuh background service** | Tinggi | Terbuka | FR-PAY-05 onboarding SOP + verifikasi lapangan. |
| R-05 | **NNAPI lebih lambat dari CPU** | Sedang | Mitigated FR-PAY-03 | Fallback chain terukur. |
| R-06 | **GNSS phone tidak mencapai akurasi absolut tinggi** | Sedang | Mitigated KPI §7 | Ukur akurasi relatif + GCP checkpoint; jangan janjikan absolut. |
| R-07 | **Regulasi frekuensi LoRa** | Sedang (hukum) | **DG-02** | Hanya relevan jika Phase 2 dijalankan. SX1262 dapat di-tune 915 atau 923 MHz. |
| R-08 | **Dataset YOLO tidak tersedia / lisensi AGPL** | Tinggi | Terbuka | SPIKE-05 sebelum menulis kode inference. |
| R-09 | **Termal payload saat capture kontinu** | Sedang | Terbuka | Interval 2–4 s, 12MP, uji 10 menit kontinu, catat throttle. |
| R-10 | **Rolling shutter + getaran drone → motion blur** | Sedang | Terbuka | Shutter ≥ 1/1000 s, damper karet, uji ketajaman lapangan. |
| R-11 | **Scope creep mode ganda** | Sedang | Terbuka | Kedua mode memakai pipeline yang sama; perbedaan hanya di lapisan metrik dan label UI. Tidak ada dua aplikasi, tidak ada dua database. |
| R-12 | **Thermal throttling laptop saat ODM panjang** | Sedang | Terbuka | Ukur suhu & clock; pertimbangkan `power-mode` Windows dan repaste jika perlu. |

### Decision Gates
* **DG-01 (SfM viability):** Lulus jika ≥ 80% foto ter-align pada MODE-B, atau ≥ 60% pada MODE-A (kanopi hidup). Gagal → MODE-B jadi mode utama. Pemilik keputusan: Tristan.
* **DG-02 (LoRa):** Diaktifkan hanya jika (a) drone tidak punya telemetry link yang bisa dipakai, dan (b) frekuensi final sudah diverifikasi regulasinya. Jangan cetak enclosure sebelum gate ini lewat.
* **DG-03 (LLM final):** Dipilih dari hasil SPIKE-04. **Status: sebagian tertutup.** Terukur pada RTX 4060 Laptop: `qwen3.5:4b-q4_K_M` = 67.1 t/s, 11.4 s wall, 3.97 GB VRAM, JSON valid 3/3 → **default produksi**. `gemma4:e4b` = 55.9 t/s, tidak dipilih. `qwen3.5:9b` dan `qwen3-vl:4b` **belum terukur** — dua kali percobaan unduh gagal (230 KB/s, lalu `503 upstream connect timeout` dari registry). Dipertimbangkan ulang hanya jika kualitas narasinya terbukti lebih baik dan tetap > 30 t/s. Rincian: `llm_benchmark_pyroscan.md`.
* **DG-04 (Kontrak advisory):** ✅ **Tertutup.** FR-SRV-06a–c diimplementasikan dan diverifikasi live di `server/llm_agent/advisory.py`. `severity` berasal dari engine, aksi dipilih dari katalog tertutup, advisory selalu punya audit trail. Self-check 10/10.

---

## 10. Changelog

### 1.3.1
* **DG-03 sebagian tertutup oleh pengukuran nyata** di RTX 4060 Laptop 8 GB. Default produksi jadi **`qwen3.5:4b-q4_K_M`** (67.1 t/s, 11.4 s, 3.97 GB). `qwen3.5:9b` dan `qwen3-vl:4b` belum terukur.
* **FR-SRV-06a–c ditambahkan:** `severity` tidak lagi diproduksi LLM; `action_items` divalidasi; advisory diberi audit trail + label draf. Dipicu temuan benchmark (4B menaikkan HIGH→CRITICAL, dan menghasilkan tindakan tidak masuk akal seperti "barikade air").
* **§2.3 VRAM budget** diganti angka terukur.
* **Dokumen baru:** `Docs/llm_benchmark_pyroscan.md` (metode, hasil, reproduksi).
* **Harness baru:** `benchmarks/bench_llm.py` (stdlib only).
* **DG-04 tertutup:** kontrak advisory diimplementasikan di `server/llm_agent/advisory.py` — katalog aksi tertutup, severity dari engine, audit trail. Diverifikasi live: sebelum `CRITICAL` + "barikade air", sesudah `HIGH` + 4 aksi katalog. Self-check 10/10.
* **Unduhan `qwen3.5:9b` gagal** dua kali (230 KB/s, lalu `503 upstream connect timeout`) — DG-03 tetap parsial tanpa internet yang memadai.

### 1.3.0
* **Scope:** tambah **dua mode misi** — MODE-A (pre-fire monitoring) dan MODE-B (burn-scar mapping). Keduanya berbagi pipeline yang sama (§1.1). Tambah FR-SRV-05 Burn Metrics.
* **LLM:** `qwen3.5:9b` (vision-capable, 5.6 GB Q4, Apache 2.0) sebagai default; `qwen3-vl:4b` sebagai fallback. Wajib `num_ctx=8192` + thinking dimatikan. DG-03 ditambahkan.
* **UI:** NodeODM + **Photogrammetry Manager** sendiri (FR-DSH-07) menggantikan UI WebODM. Tidak memakai Rust.
* **KPI:** metrik tanpa prosedur ukur dihapus (§7). Tambah "SfM success rate" sebagai KPI utama.
* **LoRa:** ditunda ke Phase 2, digabung dengan DG-02. FR-PAY-04 diganti menjadi logging lokal tanpa radio.
* **Ditambah:** FR-DSH-05 masking/culling Cesium (performa), SPIKE-04/06, R-11/R-12, NFR-MAINT-01 (dua bahasa saja).

### 1.2.0
* WebODM → **NodeODM**. Qwen2.5-VL-7B → model teks (kemudian direvisi di 1.3.0).
* Terrain tiling → `CustomHeightmapTerrainProvider`. Output `.b3dm` dihapus.
* Ditambah SQLite, FastAPI + SSE, VRAM budget, NFR-RELI-02, NFR-COST-01.
* Payload: interval 2–4 s, 12MP default, foreground service + SOP ColorOS, NNAPI fallback chain.
* Roadmap: tambah Phase 0 Technical Spike.

### 1.1.0
* Versi awal yang disetujui.
