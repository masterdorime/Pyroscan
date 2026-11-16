# Draf Isi Proposal — Bagian 3 & 4

**Versi draf:** 1.0 · **Tanggal:** 15 November 2026
**Dokumen target:** Proposal PyroScan (Google Docs)
**Status:** draf untuk direview sebelum disisipkan ke Google Docs
**Sumber:** PRD v1.3.1, `hardware_specifications_pyroscan.md` v1.2.0, `data_contracts_api_schema_pyroscan.md` v1.1.0, `llm_benchmark_pyroscan.md`, `agents_guidelines_pyroscan.md` v2.0.0, `dashboard_design.md` v0.1.0, `server/README.md`, `spike/README.md`

> **Catatan penulisan.** Blok di bawah ini adalah **tambahan** untuk bagian *3. Rancangan Sistem* dan *4. Rencana Anggaran Biaya* yang saat ini masih kosong. Tidak ada teks lama yang diubah. Penanda status dipakai konsisten: **[TERUKUR]** = sudah diuji di mesin/perangkat nyata, **[ESTIMASI]** = perkiraan berdasar spesifikasi, belum diuji, **[DIRENCANAKAN]** = belum dikerjakan.
>
> **Keputusan yang sudah dikonfirmasi (15 Nov 2026).**
> 1. Judul bagian 4 tetap **"4. Rencana Anggaran Biaya"** sesuai dokumen asli. Judul tidak diubah.
> 2. Penomoran sub-bagian: **3.1–3.9** dan **4.1–4.4**, gaya bold + nomor (bukan style Heading Google Docs).
> 3. Gaya teks target di Docs: **Arial 16**, sub-heading **bold**, tabel berlatar abu-abu pada baris header — mengikuti gaya dokumen yang sudah ada. Petunjuk markdown di bawah ini adalah representasi isi; penerjemahan ke format Docs dilakukan saat penulisan.

---

## Bagian 3 — Rancangan Sistem

### 3.1. Ringkasan Sistem

> **Catatan konsistensi dokumen.** Bagian 2 pada dokumen ini menyebut beberapa angka yang berbeda dari hasil kerja teknis terbaru: bobot payload "di bawah 100 gram" (hasil penimbangan rancangan terbaru: batas keras **190 gram**), sumber cuaca **BMKG** (implementasi memakai **Open-Meteo** dengan cache offline), dan "model Machine Learning" untuk prediksi (implementasi memakai **simulation engine deterministik** terdorong lereng dan angin, sedangkan LLM hanya menulis laporan naratif). Bagian 3 ini ditulis mengikuti hasil kerja teknis terbaru. Bagian 2 perlu diselaraskan menyusul agar tidak ada kontradiksi angka di dalam satu proposal.

PyroScan adalah sistem pemantauan, pemetaan tiga dimensi, dan prediksi rambatan kebakaran hutan yang dirancang untuk **beroperasi penuh tanpa koneksi internet**. Sistem ini tidak membangun drone dari nol. PyroScan adalah **modul ekstensi (payload)** yang dipasang di perut drone komersial yang sudah dimiliki instansi, sehingga tidak mengubah sistem kendali penerbangan drone tersebut.

Sasaran pengguna ada dua. Pertama, **komandan posko bencana atau tim SAR** yang perlu keputusan cepat soal rute evakuasi dan titik pemutusan vegetasi (*firebreak*). Kedua, **operator drone lapangan** yang memerlukan modul ringkas dan otomatis.

Sistem terdiri dari tiga lapisan yang terhubung secara berurutan:

1. **Payload (di udara).** Smartphone Android bekas **Realme 3 Pro** di dalam *tray* cetak 3D, dipasang nadir (tegak lurus ke bawah). Payload mengambil foto 12 MP ber-EXIF GPS secara berkala dan menjalankan deteksi api/asap *on-device*.
2. **Ground Station (di darat).** Laptop **Lenovo LOQ (Intel i7-HX + NVIDIA RTX 4060 8 GB)** yang menjalankan NodeODM via CUDA, verifikasi YOLO, penggabungan raster spasial, simulasi rambatan api, dan LLM advisory lokal.
3. **Dashboard (antarmuka operator).** Antarmuka 3D berbasis CesiumJS yang membaca data dari SQLite lewat FastAPI, menampilkan medan hasil rekonstruksi, hotspot, prediksi rambat, dan panel rekomendasi.

![Pipeline fotogrametri digital](references/ref-photogrammetry-process.png)

*Gambar 1. Rantai pemrosesan fotogrametri digital (SfM/MVS) yang menjadi acuan tahapan di Ground Station: penangkapan citra, ekstraksi fitur, penyesuaian berkas (*bundle adjustment*), point cloud padat, mesh, DEM, lalu orthophoto. Sumber: gambar referensi proses fotogrametri digital (bukan hasil pengukuran PyroScan).*

Sistem mendukung **dua mode misi** yang berbagi satu payload, satu pipeline, dan satu basis data. Yang berbeda hanya interpretasi hasil dan cara prediksi dihitung.

| Mode | Kapan dipakai | Sumber data | Yang dihasilkan |
|---|---|---|---|
| **MODE-A: Pre-Fire Monitoring** | Sebelum atau di depan api; area belum terbakar | Foto kanopi hidup + YOLO hotspot + DEM | Peta bahan bakar, lereng, vektor arah rambat api |
| **MODE-B: Burn-Scar Mapping** | Pasca-kebakaran | Foto permukaan hangus + DEM | Luas terbakar, batas api terakhir, topografi bekas bakar |

Alasan mode ganda bersifat teknis. Kanopi hutan hidup adalah subjek terburuk untuk *feature matching* SfM: teksturnya berulang, homogen, dan bergerak tertiup angin. Permukaan hangus justru kaya tekstur dan statis. Dengan mendukung MODE-B, proyek tetap punya jalur sukses yang terjamin meskipun MODE-A gagal di lapangan. Luas terbakar dari MODE-B juga menjadi angka validasi berguna bagi MODE-A berikutnya.

**Batasan keras yang membentuk seluruh rancangan:**

- **Offline.** Tidak ada dependensi ke cloud, CDN, atau API berbayar di jalur kritis.
- **VRAM 8 GB.** Photogrammetry dan LLM tidak boleh menempati VRAM secara bersamaan. Pelanggaran menghasilkan *out of memory*, bukan sekadar penurunan performa.
- **Satu operator.** Tanpa Redis, tanpa Celery, tanpa Postgres. Cukup SQLite dan FastAPI.
- **Dua bahasa saja.** Python untuk pipeline, TypeScript untuk antarmuka.
- **Bobot payload maksimum 190 gram.**
- **Tanpa biaya berulang.** Tidak ada layanan berlangganan dalam alur operasional.

### 3.2. Arsitektur Payload

Payload adalah Realme 3 Pro tanpa penutup belakang, dengan baterai asli dipertahankan, dipasang pada *tray* PETG cetak 3D dengan empat peredam getaran karet.

**Alur kerja aplikasi payload:**

- Berjalan sebagai *foreground service* bertipe `camera` dengan resolusi default **12 MP** (maksimum 16 MP) dan interval **2–4 detik**.
- Menyuntikkan koordinat GPS (latitud, longitud, altitud) dan waktu GNSS ke metadata EXIF setiap citra JPEG.
- Menjalankan inferensi **YOLOv8n TFLite INT8** dengan rantai delegasi yang diukur, bukan diasumsikan: `NNAPI` → `GPU delegate (FP16)` → `XNNPACK CPU (INT8)`. Delegasi tercepat yang stabil saat *startup* dipilih dan dicatat di log. **NNAPI tidak wajib berhasil**; pada Snapdragon 710, NNAPI sering memecah graf dan justru lebih lambat dari XNNPACK.
- Menyimpan seluruh hasil deteksi ke log lokal (CSV/JSON) agar tidak ada data hilang bila transfer gagal.
- Menyediakan layar panduan (*onboarding*) karena ColorOS membunuh *background service* secara agresif: izin kamera dan lokasi latar belakang, pengecualian optimasi baterai, dan izin *autostart*.

**Fase 1 berjalan tanpa radio.** Tidak ada ESP32 maupun LoRa, sehingga tidak ada kabel eksternal dan tidak ada titik gagal mekanis tambahan. *Tray* sudah dicetak dengan *pocket* kosong untuk modul radio, sehingga Fase 2 tidak memerlukan cetak ulang.

| Komponen | Spesifikasi | Fungsi |
|---|---|---|
| Realme 3 Pro (RMX1851) | Snapdragon 710, Adreno 616, Hexagon 685 | Unit pemrosesan utama: kamera, GPS, inferensi on-device |
| Sensor kamera | Sony IMX519, 16 MP (default 12 MP) | Pengambilan citra nadir ber-EXIF |
| GNSS | Multi-GNSS (GPS, GLONASS, Galileo, BeiDou) | Geotagging EXIF per citra |
| Casing tray | PETG cetak 3D, *infill* 30%, 2 perimeter | Struktur pemasangan ke perut drone |
| Peredam getaran | 4× *rubber damper ball*, rating 300 g | Menekan getaran rotor agar citra tidak *motion blur* |
| Baffle/shroud kamera | PETG hitam 5 mm di sekeliling jendela lensa | Memblokir *flare* matahari langsung |
| Sekrup, insert, velcro | — | Pengikat modul |
| ESP32-WROOM-32 + SX1262 | +22 dBm, antena 3 dBi | **Fase 2:** transmisi telemetri 16 byte |

**Batas bobot.** Total bobot Fase 1 diperkirakan **186–192 gram** terhadap batas keras 190 gram. Artinya masih mepet dan berpotensi lewat. Setiap komponen wajib ditimbang dengan timbangan dapur 0,1 gram sebelum *enclosure* final dicetak. Untuk Fase 2, dengan tambahan ESP32, modul LoRa, antena, dan kabel OTG, bobot naik ke **215–221 gram** dan **melampaui batas**. Opsi bila LoRa diaktifkan: menurunkan *infill* tray, atau melepas speaker dan modul kamera depan dari ponsel.

**Termal dan daya.** Beban capture 12 MP setiap 2 detik ditambah inferensi TFLite kontinu memanaskan sensor dan ISP; *throttling* diperkirakan muncul setelah 8–12 menit. Aturan operasional: layar dimatikan, *airplane mode* aktif (kecuali Wi-Fi saat sinkronisasi darat), dan jeda 30 detik setiap 5 menit bila suhu baterai melebihi 42 °C. Karena mode *host* OTG tidak bisa mengisi daya, batas misi per baterai diperkirakan **35–45 menit**.

### 3.3. Arsitektur Ground Station

Ground Station adalah laptop Lenovo LOQ yang menjalankan seluruh pemrosesan berat secara lokal. Alur dimulai dari *directory watcher* yang mendeteksi folder foto baru, membuat baris `mission` di basis data, lalu memicu NodeODM.

**Photogrammetry — NodeODM.** PyroScan memakai **NodeODM** langsung lewat REST API, bukan WebODM. WebODM (Django + PostGIS + antarmuka HTML) tidak dipakai di jalur kritis karena hanya sekitar 10% kemampuannya yang dibutuhkan, sementara menjadi satu titik gagal tambahan di lapangan. Penggantinya adalah halaman **Photogrammetry Manager** di dashboard PyroScan.

Seluruh opsi ODM dikirim eksplisit dari kode, tidak mengandalkan *default* container:

| Opsi ODM | Nilai | Alasan |
|---|---|---|
| `use-exif` | `true` | Memakai geotag GPS ponsel sebagai titik kontrol awal |
| `gps-accuracy` | `15` | Menoleransi ketidakpastian GNSS ponsel single-band |
| `resize-to` | `2000` | Membatasi biaya komputasi ekstraksi fitur |
| `feature-quality` | `medium` | Keseimbangan akurasi dan waktu pada 8 GB VRAM |
| `pc-quality` | `medium` | Membatasi kedalaman point cloud padat |
| `orthophoto-resolution` | `2` | Orthophoto 2 cm/piksel |
| `dem-resolution` | `2` | DEM 2 cm/piksel |
| **`dsm`** | **`true`** | **Wajib.** Tanpa opsi ini, ODM 3.6.2 mencatat `DEM will not be generated` dan tidak menghasilkan berkas DEM sama sekali |

Keluaran NodeODM: `odm_orthophoto.tif`, `odm_dem.tif`, dan `odm_textured_model_geo.glb`.

**Tahapan pipeline lengkap:**

| Tahap | Pemroses | Input | Output |
|---|---|---|---|
| Capture | Payload (Realme 3 Pro) | Perintah interval 2–4 s | Foto JPEG 12 MP + EXIF GPS |
| Deteksi tepi | YOLOv8n TFLite | Foto | Log hotspot lokal (CSV/JSON) |
| Sinkronisasi | Wi-Fi lokal posko | Folder foto | Foto di SSD laptop |
| Deteksi misi | *Directory watcher* + Mode Resolver | Folder foto baru | Baris `mission`, mode PRE_FIRE/BURN_SCAR |
| Fotogrametri | NodeODM (Docker, CUDA) | Foto + opsi eksplisit | `ortho.tif`, `dem.tif`, `mesh.glb` |
| Verifikasi visual | YOLO sisi server | Foto / orthophoto | Daftar hotspot terverifikasi |
| Fusi spasial | Python + rasterio/numpy | DEM + hotspot | `spatial_fusion.json` v1.1.0 |
| Simulasi rambat | Python + numpy | Fusi + data cuaca | Vektor prediksi 30–60 menit (MODE-A) |
| Metrik bakar | Python + rasterio | Orthophoto | Luas, keliling, bbox (MODE-B) |
| Advisory | Ollama + `qwen3.5:4b-q4_K_M` | Subset `spatial_fusion.json` | Advisory JSON + audit trail |
| Penyajian | FastAPI + SSE → CesiumJS | SQLite + aset misi | Dashboard 3D |

**Fusi raster** membaca elevasi, kelandaian (*slope*), dan arah lereng (*aspect*) dari DEM pada koordinat tepat di titik hotspot, lalu menyusunnya menjadi `spatial_fusion.json`. **Simulasi rambat** menghitung proyeksi posisi api 30–60 menit ke depan dari vektor angin dan dorongan lereng, dengan `slope_weight` dan `wind_weight` yang wajib konfigurabel untuk kalibrasi. **Burn metrics** menghitung luas, keliling, dan *bounding box* area terbakar dari klasifikasi permukaan hangus.

**Serialisasi GPU.** Photogrammetry dan LLM tidak boleh berjalan bersamaan. Alur yang diwajibkan: ODM selesai → LLM dimuat → advisory dihasilkan → model dilepas. `OLLAMA_KEEP_ALIVE=0` diset agar model tidak menahan VRAM setelah generasi selesai. VRAM efektif yang dapat dipakai hanya sekitar 7,2 GB dari 8 GB, sehingga 3,97 GB (LLM) ditambah 2–4 GB (ODM) hanya muat bila berurutan.

**Basis data dan API.** Seluruh status misi, hotspot, prediksi, cuaca, dan advisory disimpan di **SQLite** (`pyroscan.db`). Lapisan **FastAPI + uvicorn** menyajikan REST dan SSE untuk progres misi, tanpa Redis dan tanpa Celery.

### 3.4. Kontrak Data

Kontrak data adalah satu-satunya jembatan antara pipeline dan antarmuka. Semua pihak membaca format yang sama.

**`spatial_fusion.json` (versi 1.1.0).** Berkas pertukaran internal setelah fotogrametri, YOLO, dan cuaca selesai. Ini satu-satunya masukan bagi simulation engine dan LLM advisory. Field wajib: `schema_version`, `session_id`, `mission_mode`, dan `timestamp`. Struktur turunannya mencakup:

- **`photogrammetry`** — jumlah citra dikirim, jumlah citra *ter-align*, rasio, dan `rmse_reprojection_px`.
- **`hotspots`** — daftar titik dengan `lat`, `lon`, `elevation_m`, `slope_deg`, `aspect_deg`, `fire_confidence`, `smoke_confidence`.
- **`environmental_data`** — `wind_speed_kmh`, `wind_direction_deg`, `humidity_pct`, `temperature_c`, `source`, `observed_at`, dan `age_minutes`.
- **`spread_prediction`** — `predicted_lat`, `predicted_lon`, `estimated_arrival_minutes`, `risk_level`, `slope_weight`, `wind_weight`. Hanya untuk MODE-A.
- **`burn_scar`** — `area_m2`, `perimeter_m`, `bbox`, `geojson_path`. Hanya untuk MODE-B.

Satu jebakan yang harus dihindari: `wind_direction_deg` memakai konvensi meteorologis **FROM** (arah dari mana angin bertiup). Vektor rambat api adalah arah **TO**, yaitu `wind_direction_deg + 180`. Salah tanda di sini membalik seluruh prediksi.

**Advisory LLM.** Tiga aturan yang dipaksakan oleh kode, bukan sekadar imbauan:

1. **`severity` berasal dari simulation engine yang deterministik**, diteruskan apa adanya. LLM tidak pernah ditanya dan tidak pernah boleh menimpanya. Alasan konkret: pada benchmark, `qwen3.5:4b` menaikkan `HIGH` dari mesin menjadi `CRITICAL` — dua misi dengan data identik bisa memberi tingkat ancaman berbeda, dan itu tidak dapat diterima untuk keputusan evakuasi.
2. **Aksi dipilih dari katalog tertutup** berisi enam id: `EVAC_IMMEDIATE`, `EVAC_ROUTE`, `FIREBREAK`, `AERIAL`, `PATROL`, `EARLY_WARNING`. Model hanya mengembalikan `action_ids`; teksnya dirender dari katalog di server. Id di luar katalog dibuang dan dicatat di `dropped_ids`.
3. **Setiap advisory menyimpan audit trail**: `model`, `seed`, `prompt_sha`, dan `dropped_ids`. Di antarmuka, advisory selalu tampil dengan label **"draf — verifikasi lapangan"**. LLM bukan satu-satunya sumber rekomendasi SAR.

**Kontrak heightmap Cesium.** Pengganti tileset quantized-mesh, satu payload per misi:

```
{
  "mission_id": "FLIGHT_20261114_001",
  "width": 256, "height": 256,
  "west": 107.6180, "south": -6.9185,
  "east": 107.6205, "north": -6.9160,
  "height_scale_m": 1.0,
  "geoid_offset_m": -1.42,
  "heights_m": [ 748.3, 748.9, 749.4, "..." ]
}
```

`geoid_offset_m` **wajib diisi**. ODM menghasilkan tinggi di atas permukaan laut (MSL, acuan EGM96), sementara `CustomHeightmapTerrainProvider` Cesium menginterpretasikan tinggi di atas ellipsoid. Tanpa offset ini, terrain akan tampak bergeser vertikal beberapa meter dan pin hotspot tidak menempel di permukaan.

**Skema SQLite utama:**

| Tabel | Isi pokok | Kunci |
|---|---|---|
| `mission` | Mode misi, waktu mulai/selesai, luas, status pipeline, jalur DEM/ortho/mesh | `id` (mis. `FLIGHT_20261114_001`) |
| `hotspot` | Koordinat, elevasi, slope, aspect, confidence api/asap, sumber | `id`, relasi ke `mission` |
| `prediction` | Horizon (menit), koordinat prediksi, `risk_level`, bobot slope/wind | auto increment, relasi ke `hotspot` |
| `weather_obs` | Angin, kelembapan, suhu, sumber, penanda cache | auto increment, relasi ke `mission` |
| `advisory` | `severity` (dari engine), narasi, `action_ids_json`, model, `prompt_sha`, seed | `id` (mis. `ADV-20261114-01`) |

Catatan desain: `severity` di tabel `advisory` berasal dari engine, bukan model. `action_ids_json` disimpan sebagai id, bukan teks, agar kalimat bisa diubah tanpa migrasi data.

### 3.5. Dashboard 3D

Dashboard adalah konsol 3D: medan hasil rekonstruksi menjadi antarmukanya, dan panel-panel yang ada berfungsi untuk mengendalikan serta menjelaskan medan tersebut.

- **Media utama: 3D, orbit bebas.** Mode 2D adalah tombol alih, bukan tampilan utama.
- **Komposisi layar:** adegan penuh (*full-bleed*) dengan rel kanan yang bisa dilipat.
- **Basemap:** citra satelit yang di-cache lokal (2–5 km), tidak ada permintaan ke jaringan saat runtime.
- **Mode dasar:** Ortho / Elevation (/Depth) / Burn severity.
- **Overlay:** Heat, Wind, Prediction, Hotspots, Flight path — masing-masing dengan kotak centang dan penggeser opasitas, plus legenda.
- **Rel kanan:** tab Layers / Mission / Advisory / Weather, dengan lencana severity yang selalu tampil di atasnya (`LOW` hijau · `MEDIUM` kuning · `HIGH` oranye · `CRITICAL` merah, teks dan warna, tidak pernah warna saja).
- **Forecast strip** di bawah: garis waktu *now* → +60 menit, luas terbakar, laju rambat (*rate of spread*), dan peristiwa kunci.

**Kejujuran data.** Setiap lapisan yang masih berupa *fixture* diberi penanda **SIMULASI** di legenda, sampai pipeline benar-benar memproduksinya. Ini mencegah data uji terbaca sebagai hasil nyata.

![Dashboard PyroScan dengan data misi Brighton Beach](references/ref-pyroscan-live.png)

*Gambar 2. Dashboard PyroScan berjalan dengan data misi nyata dari dataset Brighton Beach: orthophoto dan mesh DSM hasil NodeODM, dibaca dari SQLite lewat FastAPI. Rel menunjukkan 18/18 foto ter-align, luas 0,71 ha, waktu proses 8 menit 27 detik, GSD 1,64 cm, dan severity MEDIUM dari engine. Lapisan heat, wind, severity, prediksi, cuaca, dan advisory masih berstatus fixture (SIMULASI). Sumber: tangkapan layar sistem PyroScan (nyata, sebagian fixture).*

Status lapisan saat ini: orthophoto, DSM/mesh, dan basemap **nyata**. Lapisan heat, wind, severity, prediksi, cuaca, dan advisory **masih fixture** yang ditandai SIMULASI. P95 *frame time* terukur sekitar 28 ms pada 1600×900 dengan seluruh lapisan aktif, dan tidak ada permintaan eksternal.

Satu koreksi teknis dari hasil spike: `CustomHeightmapTerrainProvider` Cesium menutup tepi petak ke ellipsoid sehingga tampak seperti "menara" pada skala 100 m. Solusinya adalah merender DEM sebagai *mesh primitive* dengan globe disembunyikan, yang justru selaras dengan rencana `mesh.glb` di PRD.

### 3.6. Kecerdasan Buatan dan Guardrail

Sistem memakai dua model yang berbeda peran dan tidak boleh tertukar.

**YOLOv8n di on-device.** Model INT8 berjalan di ponsel untuk mendeteksi api dan asap secara langsung di udara. Deteksi ini bersifat *preview* cepat; verifikasi kedua berjalan di sisi server setelah foto sampai di posko.

**Qwen3.5-4B via Ollama di Ground Station.** Model `qwen3.5:4b-q4_K_M` menghasilkan laporan naratif berbahasa Indonesia dari konteks spasial JSON. Hasil benchmark pada RTX 4060 Laptop 8 GB:

| Model | Decode (t/s) | Wall dingin (s) | VRAM puncak | JSON valid | Status |
|---|---|---|---|---|---|
| **`qwen3.5:4b-q4_K_M`** | **67,1 [TERUKUR]** | **11,4 [TERUKUR]** | **3,97 GB [TERUKUR]** | 3/3 | **Default produksi** |
| `gemma4:e4b` | 55,9 [TERUKUR] | 16,2 [TERUKUR] | 4,41 GB [TERUKUR] | 1/1 | Tidak dipilih |
| `qwen3.5:9b` | — | — | — | — | Belum terukur (unduhan gagal) |
| `qwen3-vl:4b` | — | — | — | — | Belum terukur (unduhan gagal) |

Latency advisory target adalah di bawah 90 detik dari status ODM `DONE` sampai advisory tersimpan. Angka terukur 11,4 detik berarti lolos dengan margin 7,9 kali. Model 4B sudah jauh melewati target; model 9B bukan syarat agar sistem berjalan, melainkan peningkatan kualitas.

**Guardrail.** Empat aturan yang tidak boleh dilonggarkan:

1. `severity` berasal dari engine, bukan dari LLM.
2. Aksi dipilih dari katalog tertutup, bukan teks bebas.
3. Jika JSON keluaran model tidak terbaca, sistem jatuh ke *fallback* dua aksi prioritas tertinggi dengan penanda `error`; advisory tidak pernah kosong.
4. `risk_level` yang tidak dikenal dipetakan ke `MEDIUM`, tidak pernah diam-diam turun ke `LOW`.

Lebih baik advisory kosong dengan penanda `error` daripada pipeline berhenti: kegagalan LLM tidak boleh menggagalkan misi.

**Keputusan DG-03 (pemilihan model) saat ini berstatus sebagian tertutup.** Model 4B terukur dan dipilih sebagai default. Dua kandidat lain belum dapat diukur karena unduhan gagal (kecepatan jaringan 210–260 KB/s, lalu `503 upstream connect timeout` dari registry).

### 3.7. Operasi Offline, Keamanan, dan Keandalan

- **Tidak ada internet di jalur kritis.** Data cuaca dari Open-Meteo diambil lewat cache offline terakhir, dan antarmuka menampilkan penanda usia data. Bila usia melewati ambang, muncul banner peringatan.
- **Tanpa Cesium ion dan tanpa CDN.** Terrain dan orthophoto dibaca dari berkas lokal; Cesium di-*mask* ke area coverage misi agar tidak merender seluruh globe dan membuang performa.
- **Keamanan API.** API LAN posko saat ini **tanpa autentikasi** karena hanya untuk prototipe. Rekomendasi untuk produksi: tambahkan token bersama sebelum API diekspos ke jaringan yang lebih luas.
- **Integritas data.** Data GPS dan *flight log* disimpan paralel di memori internal ponsel dan SSD laptop, sehingga tidak hilang bila drone mengalami musibah.
- **Ketahanan kegagalan.** Setiap tahap pipeline punya penanganan: ODM gagal → status `FAILED` dengan pesan; DEM belum siap → dashboard jatuh ke basemap 2D + pin hotspot + banner status; advisory gagal → *fallback* dengan penanda `error`.

### 3.8. Pengujian, KPI, dan Risiko

**KPI terukur.** Hanya metrik dengan prosedur ukur jelas dan sumber data yang benar-benar ada yang dipertahankan.

| Indikator | Prosedur ukur | Target MVP | Status |
|---|---|---|---|
| Deteksi api/asap YOLOv8 | mAP50 pada validation set lapangan yang di-*hold out* | > 80% | Uji belum dijalankan |
| Foto ter-align (SfM) | `num_reconstructed` ÷ `num_images` dari laporan NodeODM | > 80% MODE-B, > 60% MODE-A | 100% pada spike Brighton (permukaan, bukan kanopi) |
| Waktu proses *end-to-end* | Dari pemicu watcher sampai semua artefak tersedia di SQLite | < 4 menit (30 foto @12MP) | Belum teruji di GPU |
| Akurasi relatif orthophoto | RMSE antar ≥ 3 checkpoint GCP darat | < 2 m | Belum diukur |
| Error posisi hotspot | Jarak pin terhadap posisi api ground-truth | < 15 m | Belum diukur |
| *Frame time* dashboard | P95 *frame time* @1080p, 60 detik sampling | < 33 ms | ±28 ms pada 1600×900 [TERUKUR] |
| Latency advisory | Waktu dari status ODM `DONE` sampai advisory tersimpan | < 90 s | 11,4 s [TERUKUR] |

**Status spike yang harus dinyatakan jujur.** Pada dataset Brighton Beach (permukaan pantai, bukan kanopi hutan), 18 dari 18 foto ter-align dengan *reprojection error* 1,08 piksel dan GSD 1,64 cm, diproses 8,5 menit pada CPU. **Angka ini adalah spike pada permukaan, bukan uji kanopi hutan hidup.** SPIKE-01 (SfM di atas kanopi) masih menjadi *decision gate* yang menentukan apakah MODE-A layak diterapkan.

**Risiko dan decision gate:**

| Kode | Risiko | Dampak | Status | Mitigasi |
|---|---|---|---|---|
| R-01 | SfM gagal di atas kanopi hutan hidup | Fatal untuk MODE-A | **DG-01, blocking** | Jika gagal, MODE-B jadi mode utama; MODE-A jadi fitur eksperimental berlabel jelas |
| R-02 | Target waktu proses tidak tercapai | Tinggi | Terbuka | Turunkan resolusi/quality ODM, ukur nyata, revisi target |
| R-03 | VRAM 8 GB tidak cukup saat ODM + LLM | Tinggi | Termitigasi | Serialisasi pipeline, `OLLAMA_KEEP_ALIVE=0` |
| R-04 | ColorOS membunuh *background service* | Tinggi | Terbuka | SOP *onboarding* + verifikasi lapangan |
| R-05 | NNAPI lebih lambat dari CPU | Sedang | Termitigasi | Rantai *fallback* terukur |
| R-06 | GNSS ponsel tidak mencapai akurasi absolut tinggi | Sedang | Termitigasi | Ukur akurasi relatif + GCP; jangan menjanjikan absolut |
| R-07 | Regulasi frekuensi LoRa (Indonesia) | Sedang | **DG-02** | Hanya relevan bila Fase 2 dijalankan |
| R-08 | Dataset YOLO tidak tersedia atau lisensi AGPL | Tinggi | Terbuka | Verifikasi dataset dan lisensi sebelum menulis kode inferensi |
| R-09 | Termal payload saat capture kontinu | Sedang | Terbuka | Interval 2–4 s, 12 MP, uji 10 menit kontinu |
| R-10 | Rolling shutter + getaran → *motion blur* | Sedang | Terbuka | Shutter ≥ 1/1000 s, peredam karet, uji ketajaman |
| R-11 | *Scope creep* dua mode | Sedang | Terbuka | Satu pipeline, satu basis data; beda hanya lapisan metrik dan label |
| R-12 | *Thermal throttling* laptop saat ODM panjang | Sedang | Terbuka | Ukur suhu dan clock; atur *power mode* |

Decision gate yang mengontrol pengembangan: **DG-01** (kelayakan SfM: lulus jika ≥ 80% align pada MODE-B atau ≥ 60% pada MODE-A), **DG-02** (aktivasi LoRa, hanya bila drone tidak punya *telemetry link* dan frekuensi sudah diverifikasi), **DG-03** (pemilihan model LLM, sebagian tertutup), dan **DG-04** (kontrak advisory, sudah tertutup dan terverifikasi).

### 3.9. Roadmap Bertahap

| Fase | Fokus | Keluaran | Gate |
|---|---|---|---|
| **Fase 0 — Technical Spike** | Uji kelayakan sebelum menulis kode produksi | SfM kanopi (SPIKE-01), Camera2 level, benchmark delegasi TFLite, benchmark LLM, verifikasi dataset YOLO | **DG-01** menentukan mode utama. Status: sebagian selesai (ODM Brighton dan benchmark LLM sudah jalan; SfM kanopi, delegate TFLite, dan dataset YOLO **belum**) |
| **Fase 1 — MVP Core** | Membangun sistem jalan ujung ke ujung | Aplikasi Android capture, pipeline Python (watcher + NodeODM + YOLO + fusi + simulasi + burn metrics), SQLite + FastAPI + SSE, dashboard React + CesiumJS, Photogrammetry Manager | KPI §3.8 tervalidasi pada hardware nyata |
| **Fase 2 — Integrasi Hardware & LoRa** | Menghubungkan radio dan enclosure final | Serial USB OTG → ESP32/SX1262 + receiver posko, *enclosure* final terverifikasi bobot | **DG-02** harus lulus lebih dulu. Jangan cetak *enclosure* final sebelum gate ini lewat |
| **Fase 3 — Uji Lapangan & Kalibrasi** | Penerbangan drone nyata dan penyetelan | Uji MODE-A dan MODE-B di lapangan, kalibrasi `slope_weight` vs `wind_weight`, kalibrasi `gps-accuracy` dan penempatan GCP | Hasil kalibrasi menggantikan angka estimasi |

---

## Bagian 4 — Rencana Anggaran Biaya

> **Penting.** Seluruh angka di bagian ini adalah **estimasi pasar per November 2026**, bukan penawaran vendor. Setiap angka harus divalidasi dengan penawaran nyata sebelum diajukan sebagai komitmen. Asumsi tanggal: **November 2026**.

### 4.1. Asumsi Biaya

1. **Aset yang sudah tersedia** (bukan biaya baru, tetapi dicatat sebagai nilai aset): laptop **Lenovo LOQ RTX 4060 8 GB** dan ponsel **Realme 3 Pro**. Keduanya dianggap sudah dimiliki, sehingga tidak dihitung sebagai pengeluaran.
2. **Drone belum tersedia.** Perlu diputuskan antara menyewa/meminjam dan membeli unit bekas. Kedua skenario dihitung terpisah.
3. **Perangkat lunak open source — biaya lisensi Rp 0:** NodeODM/OpenDroneMap, Ollama, Qwen, CesiumJS, FastAPI, Python. Catatan lisensi: ODM berlisensi **AGPL-3.0**, sehingga bila perangkat lunak didistribusikan sebagai layanan jaringan, kewajiban AGPL ikut berlaku. Ultralytics (YOLOv8) juga AGPL-3.0; **lisensi komersial Ultralytics hanya diperlukan bila produk dikomersialkan.**
4. **Tanpa biaya cloud atau API berulang.** Seluruh pemrosesan lokal.
5. **Harga dicari dari sumber lokal/online** dan dicantumkan sumber serta tanggalnya pada tabel.

### 4.2. Tabel Biaya per Komponen

> Kolom harga di bawah ini **perlu diisi dengan hasil pencarian harga aktual**. Satuan: Rupiah (IDR).

**Kelompok A — Payload**

| No | Komponen | Spesifikasi | Qty | Harga Satuan (IDR) | Subtotal (IDR) | Keterangan/Sumber |
|---|---|---|---|---|---|---|
| A1 | Filamen PETG | 1 kg, 1,75 mm | 1 | ___ | ___ | Untuk tray + baffle |
| A2 | Rubber damper ball | Anti-vibrasi, rating 300 g | 4 | ___ | ___ | Peredam getaran |
| A3 | Baffle/shroud kamera | PETG hitam 5 mm (cetak) | 1 | ___ | ___ | Blokir flare |
| A4 | Sekrup, insert, velcro | Set | 1 | ___ | ___ | Pengikat modul |
| A5 | Kabel & konektor | Internal | 1 | ___ | ___ | Titik gagal minimal di Fase 1 |
| A6 | Power bank / baterai cadangan | Untuk misi panjang | 1 | ___ | ___ | Opsional |
| A7 | Realme 3 Pro | RMX1851, bekas | 1 | (aset) | **0** | **Aset tersedia**, estimasi nilai Rp ___ |

**Kelompok B — Ground Station**

| No | Komponen | Spesifikasi | Qty | Harga Satuan (IDR) | Subtotal (IDR) | Keterangan/Sumber |
|---|---|---|---|---|---|---|
| B1 | SSD NVMe | ≥ 512 GB | 1 | ___ | ___ | Satu misi ≈ 3–4 GB; sisakan ≥ 100 GB |
| B2 | Router Wi-Fi 6 portable | 5 GHz | 1 | ___ | ___ | **Wajib Fase 1** — satu-satunya jalur transfer data |
| B3 | UPS / adaptor | Daya stabil untuk ODM panjang | 1 | ___ | ___ | Cegah laptop throttle saat adaptor lepas |
| B4 | Kartu SD | ≥ 64 GB, kelas tinggi | 1 | ___ | ___ | Cadangan penyimpanan |
| B5 | Kabel & konektor | USB, LAN | 1 | ___ | ___ | — |
| B6 | Lenovo LOQ RTX 4060 | i7-HX, 8 GB VRAM | 1 | (aset) | **0** | **Aset tersedia**, estimasi nilai Rp ___ |

**Kelompok C — Drone (dua skenario)**

| Skenario | Komponen | Spesifikasi | Qty | Harga Satuan (IDR) | Subtotal (IDR) | Keterangan/Sumber |
|---|---|---|---|---|---|---|
| **C-1 Sewa** | Sewa drone | 3 hari, unit komersial kelas ringan | 1 | ___ | ___ | Opsi termurah untuk uji awal |
| **C-2 Beli** | Drone bekas | Kelas DJI Phantom 4 Pro atau Mavic 2 | 1 | ___ | ___ | Kemampuan angkat payload + baterai cadangan |

**Kelompok D — Software & Lisensi**

| No | Komponen | Spesifikasi | Qty | Harga Satuan (IDR) | Subtotal (IDR) | Keterangan/Sumber |
|---|---|---|---|---|---|---|
| D1 | NodeODM / OpenDroneMap | AGPL-3.0 | — | **0** | **0** | Kewajiban AGPL bila didistribusikan |
| D2 | Ollama + Qwen | Apache 2.0 | — | **0** | **0** | Model lokal |
| D3 | CesiumJS | Apache 2.0 | — | **0** | **0** | Tanpa Cesium ion |
| D4 | FastAPI, Python, dll. | Open source | — | **0** | **0** | — |
| D5 | Lisensi Ultralytics | Komersial (opsional) | 1 | ___ | ___ | **Hanya bila dikomersialkan** |

**Kelompok E — Pengujian Lapangan**

| No | Komponen | Spesifikasi | Qty | Harga Satuan (IDR) | Subtotal (IDR) | Keterangan/Sumber |
|---|---|---|---|---|---|---|
| E1 | Transportasi | Menuju lokasi uji | — | ___ | ___ | — |
| E2 | Akomodasi | Hari uji lapangan | — | ___ | ___ | — |
| E3 | Operator / pendamping | Harian | — | ___ | ___ | — |
| E4 | Perizinan | Bila diperlukan | — | ___ | ___ | — |
| E5 | GCP (ground control point) | Target + pengukuran | — | ___ | ___ | Untuk validasi akurasi relatif |
| E6 | Sewa lahan / akses | Bila diperlukan | — | ___ | ___ | — |

**Kelompok F — Dokumentasi & Diseminasi**

| No | Komponen | Spesifikasi | Qty | Harga Satuan (IDR) | Subtotal (IDR) | Keterangan/Sumber |
|---|---|---|---|---|---|---|
| F1 | Desain grafis | Proposal + poster | 1 | ___ | ___ | — |
| F2 | Video dokumentasi | Editing + produksi | 1 | ___ | ___ | — |
| F3 | Publikasi | Biaya publikasi | 1 | ___ | ___ | — |

**Kelompok G — Tenaga Kerja**

| No | Komponen | Spesifikasi | Qty | Harga Satuan (IDR) | Subtotal (IDR) | Keterangan/Sumber |
|---|---|---|---|---|---|---|
| G1 | Kerja mahasiswa (in-kind) | ___ jam | ___ | ___ | **in-kind** | Dihitung sebagai kontribusi, bukan pengeluaran tunai |
| G2 | Teknisi (dibiayai) | ___ hari | ___ | ___ | ___ | Bila diperlukan |

> Putuskan dan tandai dengan jelas: tenaga kerja dihitung **in-kind** (nilai kontribusi, tidak dibayar tunai) atau **dibiayai** (masuk pengeluaran). Ini memengaruhi total secara signifikan.

**Kelompok H — Kontingensi**

| No | Komponen | Spesifikasi | Qty | Harga Satuan (IDR) | Subtotal (IDR) | Keterangan/Sumber |
|---|---|---|---|---|---|---|
| H1 | Kontingensi | 10–15% dari subtotal biaya riil | 1 | ___ | ___ | Cadangan kenaikan harga / komponen gagal |

### 4.3. Ringkasan Biaya

**Total skenario minimum** (drone disewa, semua perangkat yang sudah ada, tenaga kerja in-kind): jumlahkan kelompok **A + B + C-1 + D + E + F + H** = (lihat Proposal_PyroScan.docx: minimum Rp 20.479.200 / penuh Rp 30.861.600)

**Total skenario penuh** (drone dibeli, LoRa Fase 2 disertakan, tenaga kerja sebagian dibiayai): jumlahkan kelompok **A + B + C-2 + D + E + F + G + H**, plus biaya komponen LoRa Fase 2 (ESP32 + SX1262 + antena + kabel OTG) = (lihat Proposal_PyroScan.docx: minimum Rp 20.479.200 / penuh Rp 30.861.600)

**Biaya per fase:**

| Fase | Cakupan biaya | Estimasi (IDR) |
|---|---|---|
| Fase 0 | Spike: tanpa belanja signifikan (aset sudah ada) | ≈ Rp 0 |
| Fase 1 | Payload + Ground Station + drone sewa | Rp ___ |
| Fase 2 | Modul LoRa + enclosure final + (opsi) beli drone | Rp ___ |
| Fase 3 | Uji lapangan + kalibrasi | Rp ___ |

**Biaya berulang per misi** — harus mendekati nol. Yang tersisa hanya transportasi ke lokasi dan komponen habis pakai (kabel, pengikat). Tidak ada biaya langganan, tidak ada compute cloud, tidak ada API berbayar. Estimasi per misi: (lihat Proposal_PyroScan.docx: minimum Rp 20.479.200 / penuh Rp 30.861.600)

**Tabel sensitivitas.** Bila harga drone naik 20%:

| Skenario | Asumsi drone | Total (IDR) |
|---|---|---|
| Dasar | Harga dasar | Rp ___ |
| Sensitivitas | Harga drone +20% | Rp ___ (naik sebesar 20% dari komponen drone) |

> Isi tabel setelah harga dasar drone ditentukan, agar persentase kenaikan terhadap total bisa dihitung nyata.

### 4.4. Justifikasi Nilai

**Pembanding alternatif.** Biaya PyroScan rendah karena tiga keputusan sadar:

1. **Memakai ponsel bekas sebagai payload**, bukan kamera khusus. Realme 3 Pro sudah punya sensor 16 MP, GNSS multi-sistem, dan GPU/DSP yang bisa menjalankan TFLite — semuanya tanpa pembelian perangkat baru.
2. **Memakai perangkat lunak open source.** NodeODM, Ollama, Qwen, dan CesiumJS berbiaya lisensi nol. Alternatif komersial seperti lisensi Metashape atau Pix4D berbayar per tahun, dan layanan cloud pemrosesan menambah biaya berulang per misi.
3. **Memproses secara lokal.** Seluruh komputasi berat berjalan di laptop posko. Tidak ada biaya compute atau penyimpanan cloud berulang.

Perbandingan konseptual dengan alternatif yang lebih mahal:

| Alternatif | Mengapa berbeda dari PyroScan |
|---|---|
| Drone RTK + kamera multispektral | Presisi absolut jauh lebih tinggi, tetapi biaya perangkat berkali-kali lipat dan operatornya terspesialisasi |
| Lisensi perangkat lunak fotogrametri komersial | Berbiaya berulang per tahun, sedangkan PyroScan memakai ODM yang open source |
| Layanan pemrosesan cloud | Membutuhkan internet, yang bertentangan langsung dengan batasan operasi offline PyroScan |

**Batasan yang harus dinyatakan jujur:**

- PyroScan **tidak mengklaim akurasi absolut**. GNSS ponsel single-band sambil bergerak tidak bisa menjamin akurasi di bawah 5 meter. Yang diukur adalah akurasi relatif antar checkpoint GCP.
- **Biaya validasi GCP/RTK dihitung terpisah.** Bila proyek menuntut akurasi absolut, perlu peralatan atau jasa pengukuran tambahan di luar anggaran ini.
- Harga drone bekas sangat bergantung pada kondisi unit dan ketersediaan pasar lokal, sehingga rentangnya lebar dan perlu diverifikasi langsung.

---

## Lampiran — Daftar Gambar dan Status

| Gambar | Berkas | Apa yang ditunjukkan | Status |
|---|---|---|---|
| Gambar 1 | `Docs/references/ref-photogrammetry-process.png` | Rantai proses fotogrametri digital (SfM/MVS) | Referensi (bukan hasil PyroScan) |
| Gambar 2 | `Docs/references/ref-pyroscan-live.png` | Dashboard PyroScan dengan data misi Brighton Beach | Nyata (sebagian lapisan fixture) |
| Gambar 3 (opsi) | `Docs/references/ref-elevation.png` | Permukaan elevasi / point cloud | Referensi visual |
| Gambar 4 (opsi) | `Docs/references/ref-burn-severity.png` | Pita kelas burn severity | Referensi visual |
| Gambar 5 (opsi) | `simulation/shots/FINAL-default.png` | Studio payload 3D (tray + ponsel) | Simulasi |

Maksimal 4–5 gambar. Pilih sesuai kebutuhan; jangan memenuhi dokumen dengan gambar.

---

## Catatan Reviewer — Status

1. **Angka harga** pada §4.2, §4.3: kosong dan perlu diisi. **Masih terbuka — menunggu angka dari Anda.**
2. **Tenaga kerja** (§4.2 G): in-kind atau dibiayai? **Masih terbuka.**
3. **Drone**: sewa 3 hari atau beli bekas? **Kedua skenario sudah disiapkan** (C-1 dan C-2).
4. ✅ **SELESAI** — Judul bagian 4 memakai **"4. Rencana Anggaran Biaya"** sesuai dokumen asli.
5. ✅ **SELESAI** — Sub-heading memakai penomoran `3.1`, `3.2`, … gaya bold, mengikuti dokumen.
