# Hardware Specification — PyroScan Extension Payload

**Version:** 1.2.0
**Related:** `product_requirement_document_pyroscan_prd.1.md` v1.3.0

> **Changelog 1.2.0** — Tambah §5 frekuensi & regulasi, §6 weight budget, §7 termal & daya, §8 verification checklist. Camera2 level ditandai wajib verifikasi. LoRa dipindah ke Phase 2.

---

## 1. Overview & Mechanical Design

Modul *extension payload* PyroScan dirancang untuk dipasang di bawah perut drone (*belly mount*) dengan posisi **Top-Down (Nadir)**, yaitu layar smartphone mendatar sejajar tanah dan kamera utama menghadap tegak lurus $90^\circ$ ke permukaan bumi.

```
+-------------------------------------------------------------+
|                     DRONE MAIN FRAME                        |
+------------------------------+------------------------------+
                               | (4x Rubber Vibration Damper)
                               v
+-------------------------------------------------------------+
|            PAYLOAD TRAY FRAME (3D PRINT PETG)               |
|                                                             |
|  [ ESP32 LoRa* ] <--(USB OTG)--> [ REALME 3 PRO (FLAT) ]    |
|  * Phase 2 only                   kamera menghadap kebawah  |
|                                       || (Sony IMX519)      |
+---------------------------------------||--------------------+
                                        \/
                                 (Top-Down Aerial Photo)
```

**Phase 1** tidak menyertakan ESP32/LoRa. Tray dicetak dengan *pocket* kosong untuk modul radio agar tidak perlu mencetak ulang saat Phase 2.

---

## 2. Component Specifications

### 2.1. Primary Processing Unit (Smartphone)
* **Model:** Realme 3 Pro (RMX1851).
* **Processor:** Qualcomm Snapdragon 710 (10nm Octa-Core).
* **GPU / AI Accelerator:** Adreno 616 GPU + Hexagon 685 DSP (NNAPI supported).
* **Camera System:** 16 MP Sony IMX519 Sensor ($f/1.7$, $1/2.6"$ sensor size).
* **Positioning:** Multi-GNSS (GPS, GLONASS, GALILEO, BeiDou).
* **Weight Reduction:** Backcover plastik dilepas, baterai asli dipertahankan. Total bobot net: **~155 gram**.

> **⚠️ Camera2 Level — wajib diverifikasi sebelum desain final.**
> Cek `CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL`. Realme 3 Pro pada Android 9/10 kemungkinan hanya `LEGACY` atau `LIMITED`, bukan `FULL`. Konsekuensi bila `LIMITED`:
> * Kontrol `SENSOR_EXPOSURE_TIME` manual mungkin tidak tersedia → auto-exposure akan menurunkan shutter di bawah 1/1000 s saat mendung, menghasilkan motion blur.
> * `CONTROL_AE_TARGET_FPS_RANGE` mungkin terbatas.
> * Buffer burst mungkin < 3 frame.
>
> Jika level terbukti `LEGACY`, mitigasi: gunakan mode video 1080p60 sebagai sumber frame (bukan still capture), atau buka kompensasi exposure (`CONTROL_AE_EXPOSURE_COMPENSATION` / `SENSOR_SENSITIVITY`) sebagai gantinya.

### 2.2. Radio Transceiver Unit (Phase 2 only)
* **Microcontroller:** ESP32-WROOM-32.
* **LoRa Chipset:** Semtech SX1262 (tunable 915 / 923 MHz — lihat §5).
* **Output Power:** $+22\text{ dBm}$ (Transmit Range up to $3–5\text{ km}$ line-of-sight).
* **Antenna:** $3\text{ dBi}$ Dipole Rubber Antenna with SMA connector.
* **Status:** **Tidak dipasang di Phase 1.** Lihat DG-02 di PRD §9.

### 2.3. Mechanical & Mounting
* **Structure:** 3D Printed Frame Tray menggunakan filament **PETG** (tahan panas outdoor & fleksibel).
* **Damping System:** 4x Blue Rubber Anti-Vibration Balls (300g load rating).
* **Camera Window:** Cut-out hole sebesar $30 \times 20\text{ mm}$ persis di bawah posisi lensa Sony IMX519.
* **Lens Shroud (disarankan):** baffle PETG hitam 5 mm di sekeliling jendela kamera untuk memblokir flare matahari langsung. Tanpa ini, foto nadir siang hari akan berkontras rendah dan memperburuk feature matching.

---

## 3. Electrical & Wiring Diagram

### 3.1. Phase 1 (tanpa LoRa)
```
[ Realme 3 Pro ] --(internal)--> capture + log + Wi-Fi sync
```
Tidak ada wiring eksternal. Kabel = nol titik gagal tambahan.

### 3.2. Phase 2 (dengan LoRa)
```text
[ Realme 3 Pro ] --(USB-C OTG Cable)--> [ ESP32 Microcontroller ]
  - VBUS (+5V)   --------------------->   - VIN / 5V Pin
  - Data (D+)    --------------------->   - USB Bridge (CP2102/CH340)
  - Data (D-)    --------------------->   - USB Bridge (CP2102/CH340)
  - Ground (GND) --------------------->   - GND Pin

[ ESP32 Microcontroller ] <--(SPI Interface)--> [ SX1262 LoRa Module ]
  - GPIO 5 (CS)  --------------------->   - NSS / CS
  - GPIO 18 (SCK)--------------------->   - SCK
  - GPIO 19 (MISO)-------------------->   - MISO
  - GPIO 23 (MOSI)-------------------->   - MOSI
  - GPIO 14 (RST) --------------------->   - NRESET
  - GPIO 26 (DIO1)-------------------->   - DIO1
```

**Catatan OTG:**
* Saat USB-C host mode aktif, HP **tidak dapat mengisi daya**. Batas waktu misi = kapasitas baterai HP (~4000 mAh) dikurangi konsumsi capture + inferensi. Estimasi aman: **35–45 menit** penerbangan per baterai.
* Kabel OTG adalah titik gagal mekanis paling rapuh pada payload. Gunakan kabel dengan *strain relief* dan kunci dengan *hot glue* atau *cable tie* ke tray — bukan menggantung bebas.

---

## 4. Ground Station Hardware Setup

* **Laptop Workstation:** Lenovo LOQ Series (Intel Core i7 HX-series, NVIDIA RTX 4060 8GB GDDR6, 16/32GB RAM).
* **Receiver Unit:** ESP32 + SX1262 LoRa Receiver via USB Serial ke laptop posko. *(Phase 2)*
* **Local Access Point:** Router Wi-Fi 6 Portable ($5\text{ GHz}$) di posko darat untuk *bulk auto-sync* foto saat drone mendarat. **Wajib ada di Phase 1** — ini satu-satunya jalur transfer data.
* **Storage:** SSD NVMe ≥ 512 GB. Satu misi 30 menit @2 s interval @12MP ≈ 900 foto ≈ 3–4 GB. Sisakan ≥ 100 GB bebas untuk dataset ODM.

---

## 5. Frekuensi & Regulasi

Ini **bukan** keputusan teknis, dan tidak boleh ditetapkan di dokumen tanpa verifikasi.

| Parameter | Nilai | Status |
|---|---|---|
| Frekuensi di PRD v1.1.0 | 915 MHz | ❌ Kemungkinan **bukan** alokasi ISM Indonesia |
| Alokasi ISM Indonesia (indikatif) | 920–923 MHz | ⚠️ **Harus diverifikasi** ke SDPPI/Komdigi |
| SX1262 | Tunable 150–960 MHz | ✅ Mendukung keduanya |
| Daya pancar | +22 dBm | ⚠️ Batas EIRP per band perlu dicek |

**Status: DG-02, terbuka.** Jangan cetak enclosure final dan jangan pesan antena sebelum:
1. Alokasi frekuensi ISM Indonesia yang berlaku dikonfirmasi.
2. Batas daya pancar untuk band tersebut diketahui.
3. Kebutuhan perizinan (jika ada) dipahami.

Karena LoRa sudah dipindah ke Phase 2, gate ini **tidak menghambat Phase 1**.

---

## 6. Weight Budget (Hard Cap: 190 g)

| Komponen | Estimasi | Catatan |
|---|---|---|
| Realme 3 Pro tanpa backcover, baterai asli | 155 g | Angka dari spec, **verifikasi dengan timbangan** |
| Tray PETG (infill 30%, 2 perimeter) | 18–24 g | Bervariasi menurut slicer |
| 4x rubber damper ball + pengikat | 6 g | |
| Baffle/shroud kamera (PETG) | 2 g | |
| Sekrup, insert, velcro | 5 g | |
| **Subtotal Phase 1** | **186–192 g** | **⚠️ Mepet / berpotensi lewat** |
| ESP32-WROOM-32 + breakout | 8 g | Phase 2 |
| SX1262 module | 3 g | Phase 2 |
| Antena 3 dBi + SMA | 12 g | Phase 2 |
| Kabel OTG | 6 g | Phase 2 |
| **Subtotal Phase 2** | **215–221 g** | **❌ Melebihi cap** |

**Kesimpulan:** Phase 1 kemungkinan masih lolos (mepet). **Phase 2 tidak lolos** dengan angka ini. Opsi bila LoRa diaktifkan:
1. Turunkan infill tray ke 15–20% dan gunakan *sparse* top/bottom.
2. Ganti baterai HP dengan sel lebih kecil (risiko: runtime turun).
3. Lepas speaker, getaran motor, dan modul kamera sekunder depan dari HP.
4. Revisi NFR-PERF-01 dengan justifikasi tertulis.

**Wajib:** timbang setiap komponen dengan timbangan dapur 0.1 g sebelum enclosure final dicetak. Jangan pakai angka spec sebagai kebenaran.

---

## 7. Termal & Manajemen Daya

### 7.1. Payload (Realme 3 Pro)
| Beban | Dampak |
|---|---|
| Capture 12MP @2 s | Sensor + ISP panas, throttle setelah ~8–12 menit |
| TFLite INT8 kontinu | Adreno/Hexagon panas, throttle lebih cepat |
| Layar menyala | Konsumsi besar & panas — **matikan layar** atau set brightness 0 |
| Charging saat terbang | Tidak mungkin (OTG host mode) |

**Aturan operasional:**
* Default **12MP @2–4 s**, bukan 16MP @1 s.
* Layar mati, airplane mode ON (kecuali Wi-Fi saat sinkronisasi darat).
* Jeda 30 detik setiap 5 menit capture bila suhu baterai > 42 °C (baca `BatteryManager.EXTRA_TEMPERATURE`).
* Catat suhu awal/akhir ke log — ini data validasi untuk SPIKE-03.

### 7.2. Ground Station (Lenovo LOQ)
* ODM adalah beban CPU+GPU kontinu 3–10 menit → laptop *thermal throttle*.
* Set Windows power mode ke **Best Performance** dan pastikan adaptor terpasang.
* Letakkan laptop di permukaan keras dan berventilasi — bukan di pangkuan atau di dalam tas.
* Ukur `nvidia-smi` clocks & suhu selama task ODM; simpan sebagai baseline di SPIKE-04.

---

## 8. Verification Checklist (Pre-Flight)

Dijalankan sebelum penerbangan pertama dan setelah setiap perubahan firmware.

### 8.1. Payload
- [ ] `INFO_SUPPORTED_HARDWARE_LEVEL` tercatat (LEGACY / LIMITED / FULL)
- [ ] Exposure manual tersedia? (ya/tidak) → catat nilai shutter & ISO yang dipakai
- [ ] GNSS fix < 30 s, `num_satellites` ≥ 6, `horizontal_accuracy` tercatat
- [ ] Foreground service `camera` bertahan 10 menit dengan layar mati
- [ ] Battery optimization dimatikan untuk aplikasi
- [ ] Autostart ColorOS diizinkan
- [ ] 100 foto test tersimpan, EXIF GPS terbaca oleh `exiftool`
- [ ] Suhu baterai setelah 10 menit capture tercatat
- [ ] **Bobot total ditimbang** (target < 190 g)

### 8.2. Delegate Benchmark (SPIKE-03)
- [ ] NNAPI: FPS ____ , suhu akhir ____
- [ ] GPU delegate FP16: FPS ____ , suhu akhir ____
- [ ] XNNPACK CPU INT8: FPS ____ , suhu akhir ____
- [ ] Delegate terpilih: __________ (alasan: __________)

### 8.3. SfM Viability (SPIKE-01 / DG-01)
- [ ] 20–30 foto nadir kanopi hidup diambil
- [ ] `num_reconstructed / num_images` = ____ %
- [ ] RMSE reprojection = ____ px
- [ ] DEM terbentuk? (ya/tidak)
- [ ] Waktu proses = ____ menit
- [ ] **DG-01 lulus?** (MODE-A ≥ 60%, MODE-B ≥ 80%)

### 8.4. Ground Station
- [ ] NodeODM container jalan, GPU terdeteksi (`--gpu`)
- [ ] `nvidia-smi` melihat proses ODM
- [ ] Demo kecil (5 foto) menghasilkan `ortho.tif` + `dem.tif` + `mesh.glb`
- [ ] Ollama melayani `qwen3.5:4b-q4_K_M` dengan `num_ctx=8192`
- [ ] VRAM peak tercatat saat ODM saja, LLM saja, dan keduanya berurutan
- [ ] `OLLAMA_KEEP_ALIVE=0` terbukti membebaskan VRAM setelah generasi
- [ ] `python benchmarks\bench_llm.py --repeats 3 qwen3.5:4b-q4_K_M` menghasilkan wall < 30 s

> Baseline terukur (2026-11-14, RTX 4060 Laptop 8 GB): 67.1 t/s decode, 11.4 s wall, 3.97 GB VRAM, JSON valid 3/3. Lihat `llm_benchmark_pyroscan.md`.
