# Hardware Specification — PyroScan Extension Payload

**Version:** 1.2.0
**Related:** `product_requirement_document_pyroscan_prd.1.md` v1.3.1

> **Changelog 1.2.0** — Added §5 frequency & regulation, §6 weight budget, §7 thermal & power, §8 verification checklist. Camera2 level flagged as requiring verification. LoRa moved to Phase 2.

---

## 1. Overview & Mechanical Design

The PyroScan *extension payload* is designed to mount under the drone's belly (*belly mount*) in a **top-down (nadir)** orientation — the phone lies flat, parallel to the ground, with the main camera pointing straight down at $90^\circ$ to the surface.

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
|  * Phase 2 only                   camera facing down         |
|                                       || (Sony IMX519)      |
+---------------------------------------||--------------------+
                                        \/
                                 (Top-Down Aerial Photo)
```

**Phase 1** does not include the ESP32/LoRa. The tray is printed with an empty *pocket* for the radio module so it does not have to be reprinted when Phase 2 arrives.

---

## 2. Component Specifications

### 2.1. Primary Processing Unit (Smartphone)
* **Model:** Realme 3 Pro (RMX1851).
* **Processor:** Qualcomm Snapdragon 710 (10nm octa-core).
* **GPU / AI accelerator:** Adreno 616 GPU + Hexagon 685 DSP (NNAPI supported).
* **Camera system:** 16 MP Sony IMX519 sensor ($f/1.7$, $1/2.6"$ sensor size).
* **Positioning:** Multi-GNSS (GPS, GLONASS, GALILEO, BeiDou).
* **Weight reduction:** plastic back cover removed, original battery retained. Net weight: **~155 g**.

> **⚠️ Camera2 level — must be verified before the design is final.**
> Check `CameraCharacteristics.INFO_SUPPORTED_HARDWARE_LEVEL`. On Android 9/10 the Realme 3 Pro is likely `LEGACY` or `LIMITED`, not `FULL`. Consequences if `LIMITED`:
> * Manual `SENSOR_EXPOSURE_TIME` control may be unavailable → auto-exposure will drop the shutter below 1/1000 s on an overcast day, producing motion blur.
> * `CONTROL_AE_TARGET_FPS_RANGE` may be constrained.
> * Burst buffering may be under 3 frames.
>
> If the level turns out to be `LEGACY`, mitigate by using 1080p60 video as the frame source (instead of still capture), or expose `CONTROL_AE_EXPOSURE_COMPENSATION` / `SENSOR_SENSITIVITY` as a substitute.

### 2.2. Radio Transceiver Unit (Phase 2 only)
* **Microcontroller:** ESP32-WROOM-32.
* **LoRa chipset:** Semtech SX1262 (tunable 915 / 923 MHz — see §5).
* **Output power:** $+22\text{ dBm}$ (range up to $3–5\text{ km}$ line-of-sight).
* **Antenna:** $3\text{ dBi}$ dipole rubber antenna with SMA connector.
* **Status:** **not fitted in Phase 1.** See DG-02 in PRD §9.

### 2.3. Mechanical & Mounting
* **Structure:** 3D-printed frame tray in **PETG** (outdoor heat resistant and slightly flexible).
* **Damping system:** 4× blue rubber anti-vibration balls (300 g load rating).
* **Camera window:** cut-out of $30 \times 20\text{ mm}$ directly under the Sony IMX519 lens.
* **Lens shroud (recommended):** a 5 mm black PETG baffle around the camera window to block direct sun flare. Without it, midday nadir photos come out low-contrast, which makes feature matching worse.

---

## 3. Electrical & Wiring Diagram

### 3.1. Phase 1 (no LoRa)
```
[ Realme 3 Pro ] --(internal)--> capture + log + Wi-Fi sync
```
No external wiring. Zero additional mechanical failure points.

### 3.2. Phase 2 (with LoRa)
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

**OTG notes:**
* While USB-C host mode is active, the phone **cannot charge**. Mission duration is therefore the phone's battery capacity (~4000 mAh) minus capture and inference draw. Safe estimate: **35–45 minutes** of flight per battery.
* The OTG cable is the most fragile mechanical point on the payload. Use a cable with strain relief and secure it to the tray with hot glue or a cable tie — do not let it hang free.

---

## 4. Ground Station Hardware Setup

* **Laptop workstation:** Lenovo LOQ series (Intel Core i7 HX-series, NVIDIA RTX 4060 8 GB GDDR6, 16/32 GB RAM).
* **Receiver unit:** ESP32 + SX1262 LoRa receiver over USB serial to the command-post laptop. *(Phase 2)*
* **Local access point:** portable Wi-Fi 6 router ($5\text{ GHz}$) at the command post for *bulk auto-sync* when the drone lands. **Required in Phase 1** — it is the only data transfer path.
* **Storage:** NVMe SSD ≥ 512 GB. One 30-minute mission at a 2 s interval and 12 MP ≈ 900 photos ≈ 3–4 GB. Keep ≥ 100 GB free for ODM scratch data.

---

## 5. Frequency & Regulation

This is **not** a technical decision and must not be settled in a document without verification.

| Parameter | Value | Status |
|---|---|---|
| Frequency in PRD v1.1.0 | 915 MHz | ❌ likely **not** the Indonesian ISM allocation |
| Indonesian ISM allocation (indicative) | 920–923 MHz | ⚠️ **must be verified** with SDPPI/Komdigi |
| SX1262 | tunable 150–960 MHz | ✅ supports both |
| Output power | +22 dBm | ⚠️ the EIRP limit per band must be checked |

**Status: DG-02, open.** Do not print the final enclosure or order the antenna before:
1. The applicable Indonesian ISM frequency allocation is confirmed.
2. The transmit-power limit for that band is known.
3. Any licensing requirement is understood.

Because LoRa is deferred to Phase 2, this gate **does not block Phase 1**.

---

## 6. Weight Budget (Hard Cap: 190 g)

| Component | Estimate | Note |
|---|---|---|
| Realme 3 Pro without back cover, original battery | 155 g | from spec — **verify on a scale** |
| PETG tray (30% infill, 2 perimeters) | 18–24 g | slicer dependent |
| 4× rubber damper balls + ties | 6 g | |
| Camera baffle/shroud (PETG) | 2 g | |
| Screws, inserts, velcro | 5 g | |
| **Phase 1 subtotal** | **186–192 g** | **⚠️ tight / possibly over** |
| ESP32-WROOM-32 + breakout | 8 g | Phase 2 |
| SX1262 module | 3 g | Phase 2 |
| 3 dBi antenna + SMA | 12 g | Phase 2 |
| OTG cable | 6 g | Phase 2 |
| **Phase 2 subtotal** | **215–221 g** | **❌ exceeds the cap** |

**Conclusion:** Phase 1 probably still passes (barely). **Phase 2 does not pass** with these figures. If LoRa is enabled, either:
1. Drop tray infill to 15–20% and use sparse top/bottom.
2. Replace the phone battery with a smaller cell (risk: shorter runtime).
3. Remove the speaker, vibration motor, and front secondary camera module from the phone.
4. Revise NFR-PERF-01 with written justification.

**Mandatory:** weigh every component on a 0.1 g kitchen scale before printing the final enclosure. Do not treat spec-sheet numbers as truth.

---

## 7. Thermal & Power Management

### 7.1. Payload (Realme 3 Pro)
| Load | Effect |
|---|---|
| 12 MP capture @2 s | Sensor + ISP heat up, throttling after ~8–12 minutes |
| Continuous TFLite INT8 | Adreno/Hexagon heat up, throttles sooner |
| Screen on | Large draw and heat — **turn the screen off** or set brightness to 0 |
| Charging in flight | Impossible (OTG host mode) |

**Operating rules:**
* Default **12 MP @2–4 s**, not 16 MP @1 s.
* Screen off, airplane mode on (except Wi-Fi during ground sync).
* Pause 30 s every 5 minutes of capture if battery temperature > 42 °C (read `BatteryManager.EXTRA_TEMPERATURE`).
* Log start/end temperature — that is the validation data for SPIKE-03.

### 7.2. Ground Station (Lenovo LOQ)
* ODM is a continuous CPU+GPU load for 3–10 minutes → the laptop *thermal throttles*.
* Set Windows power mode to **Best Performance** and keep the adapter connected.
* Put the laptop on a hard, ventilated surface — not a lap, not inside a bag.
* Record `nvidia-smi` clocks and temperature during an ODM task; keep it as the SPIKE-04 baseline.

---

## 8. Verification Checklist (Pre-Flight)

Run before the first flight and after every firmware change.

### 8.1. Payload
- [ ] `INFO_SUPPORTED_HARDWARE_LEVEL` recorded (LEGACY / LIMITED / FULL)
- [ ] Manual exposure available? (yes/no) → record the shutter and ISO used
- [ ] GNSS fix < 30 s, `num_satellites` ≥ 6, `horizontal_accuracy` recorded
- [ ] `camera` foreground service survives 10 minutes with the screen off
- [ ] Battery optimization disabled for the app
- [ ] ColorOS autostart allowed
- [ ] 100 test photos stored, EXIF GPS readable by `exiftool`
- [ ] Battery temperature after 10 minutes of capture recorded
- [ ] **Total weight weighed** (target < 190 g)

### 8.2. Delegate Benchmark (SPIKE-03)
- [ ] NNAPI: FPS ____ , final temperature ____
- [ ] GPU delegate FP16: FPS ____ , final temperature ____
- [ ] XNNPACK CPU INT8: FPS ____ , final temperature ____
- [ ] Delegate selected: __________ (reason: __________)

### 8.3. SfM Viability (SPIKE-01 / DG-01)
- [ ] 20–30 nadir photos of a living canopy captured
- [ ] `num_reconstructed / num_images` = ____ %
- [ ] Reprojection RMSE = ____ px
- [ ] DEM generated? (yes/no)
- [ ] Processing time = ____ minutes
- [ ] **DG-01 passes?** (MODE-A ≥ 60%, MODE-B ≥ 80%)

### 8.4. Ground Station
- [ ] NodeODM container running, GPU detected (`--gpu`)
- [ ] `nvidia-smi` sees the ODM process
- [ ] Small demo (5 photos) produces `ortho.tif` + `dem.tif` + `mesh.glb`
- [ ] Ollama serves `qwen3.5:4b-q4_K_M` with `num_ctx=8192`
- [ ] VRAM peak recorded for ODM alone, LLM alone, and both in sequence
- [ ] `OLLAMA_KEEP_ALIVE=0` demonstrably frees VRAM after generation
- [ ] `python benchmarks\bench_llm.py --repeats 3 qwen3.5:4b-q4_K_M` reports wall < 30 s

> Measured baseline (2026-11-14, RTX 4060 Laptop 8 GB): 67.1 t/s decode, 11.4 s wall, 3.97 GB VRAM, valid JSON 3/3. See `llm_benchmark_pyroscan.md`.
