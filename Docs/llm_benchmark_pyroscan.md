# LLM Benchmark — Ground Station (SPIKE-04 / DG-03)

**Status:** Partial — 2 dari 4 kandidat terukur
**Tanggal:** 2026-11-14
**Hardware:** Lenovo LOQ, RTX 4060 Laptop **8 GB** (8188 MiB), driver 581.86
**Runtime:** Ollama 0.40.5, Python 3.14.7
**Harness:** `benchmarks/bench_llm.py` (stdlib only)

---

## 1. Mengapa benchmark ini ada

PRD v1.3.0 §9 DG-03 mewajibkan model LLM dipilih dari hasil pengukuran, bukan dari tabel benchmark internet. Semua angka di dokumen PRD sebelumnya adalah **estimasi pihak ketiga**. Dokumen ini menggantinya dengan angka dari mesin yang benar-benar akan dipakai di posko.

## 2. Metode

Beban kerja = **persis yang diminta FR-SRV-06**: JSON spasial masuk → advisory JSON keluar.

| Parameter | Nilai |
|---|---|
| `num_ctx` | 8192 (eksplisit; Ollama default memilih 4K di < 24 GiB) |
| `temperature` / `seed` | 0.2 / 42 (deterministik) |
| `format` | `json` (structured output, sesuai kontrak) |
| `think` | `false` (matikan reasoning trace) |
| `keep_alive` | `0` → **setiap run membayar cold load**, sama seperti pipeline nyata yang membebaskan VRAM untuk NodeODM |
| Panjang prompt | ~230 token (14 field spasial + instruksi) |
| Output target | ~150–190 token |

**Cara ukur:**
* Throughput decode & prefill diambil dari field `eval_duration` / `prompt_eval_duration` milik Ollama sendiri (nanodetik), bukan dari stopwatch.
* VRAM peak disampling `nvidia-smi --loop-ms=100` lewat satu proses panjang selama request berjalan.
* Model di-*unload* (`keep_alive: 0`) sebelum setiap run agar tiap run mengukur cold start.
* Placement GPU dibaca lewat probe terpisah setelah trial (`/api/ps` tidak bisa dipoll saat generasi berjalan — Ollama melayani satu request sekaligus).
* Repeat: 3× untuk model utama (diambil median), 1× untuk model pembanding.

---

## 3. Hasil terukur

| Model | Decode (t/s) | Prefill (t/s) | Wall, cold (s) | Output (tok) | VRAM peak | Placement | JSON valid |
|---|---|---|---|---|---|---|---|
| `qwen3.5:4b-q4_K_M` | **67.1** | 1112.5 | **11.4** | 152 | +3.97 GB | 100% GPU | 3/3 |
| `gemma4:e4b` | 55.9 | 895.7 | 16.2 | 190 | +4.41 GB | 100% GPU | 1/1 |

Catatan: `gemma4:e4b` dilaporkan 9.6 GB saat pull, tetapi build yang dimuat hanya menempati ~4.4 GB VRAM dan berjalan 100% GPU. Ukuran unduhan ≠ jejak VRAM.

### 3.1. Belum terukur

| Model | Alasan |
|---|---|
| `qwen3.5:9b` (~5.6 GB) | Unduhan terhenti di 9% — kecepatan jaringan 210–260 KB/s, estimasi > 1 jam per model |
| `qwen3-vl:4b` (~3.3 GB) | Sama; dibatalkan agar tidak mengacaukan pengukuran (disk + bandwidth contention) |

Blob parsial tersimpan dan pull bisa dilanjutkan kapan saja. Jalankan:

```powershell
ollama pull qwen3.5:9b
ollama pull qwen3-vl:4b
python benchmarks\bench_llm.py --repeats 3 qwen3.5:9b qwen3-vl:4b
```

---

## 4. Uji terhadap KPI PRD §7

| KPI | Target | Terukur | Status |
|---|---|---|---|
| Latency advisory (ODM DONE → advisory tersimpan) | < 90 s | **11.4 s** (termasuk cold load) | ✅ lulus 7.9× |
| Kualitas JSON kontrak | parse + 3 keys + ≥3 action items | 3/3 run | ✅ lulus |

**Kesimpulan penting:** model 4B sudah **jauh** melewati KPI latency. Model 9B bukan syarat agar sistem jalan — ia peningkatan kualitas, bukan kebutuhan. Ini menurunkan urgensi unduhan 5.6 GB.

---

## 5. Temuan kualitas (lebih penting dari throughput)

Kedua model menghasilkan bahasa Indonesia yang wajar dan JSON valid. Tapi ada dua masalah yang harus ditangani di kode, bukan di dokumen:

### 5.1. LLM mengubah `severity` yang diberikan model numerik

Input menyatakan `risk_level: HIGH` dari simulation engine. Hasil:

| Model | severity keluaran |
|---|---|
| `qwen3.5:4b-q4_K_M` | **CRITICAL** ← naik satu tingkat |
| `gemma4:e4b` | HIGH |

**Rekomendasi:** `severity` **tidak boleh** diproduksi oleh LLM. Nilai itu harus berasal dari simulation engine yang deterministik; LLM hanya menulis `summary_narrative` dan `action_items`. Kalau tidak, dua misi dengan data identik bisa memberi tingkat ancaman berbeda — tidak dapat diterima untuk keputusan evakuasi.

### 5.2. Terdapat tindakan yang tidak masuk akal secara teknis

`qwen3.5:4b-q4_K_M` menghasilkan *"Tim SAR membentuk barikade air di jalur prediksi"*. Barikade air tidak menghentikan kebakaran hutan; ini halusinasi domain. `gemma4:e4b` menulis *"jalur evakuasi alternatif yang menjauhi arah angin (barat daya ke timur laut)"* — arah yang disebut justru arah **rambat** api, bukan arah menjauh.

**Rekomendasi:**
1. `action_items` dibatasi ke kosakata tindakan yang sudah ada (evakuasi, firebreak, rute, koordinasi) lewat prompt enumerasi + validasi pasca-generasi.
2. Setiap advisory wajib punya disclaimer + tombol "ini draf, verifikasi lapangan" di dashboard. LLM tidak boleh menjadi satu-satunya sumber rekomendasi SAR.
3. Simpan `prompt_sha` + `model` + `seed` di tabel advisory untuk audit.

---

### 5.3. Perbaikan dan verifikasi

Kedua cacat di atas ditutup di kode, bukan di prompt: `server/llm_agent/advisory.py`.

| Mekanisme | Efek |
|---|---|
| `severity` diambil dari `fusion.risk_level`, tidak pernah diminta ke model | LLM tidak punya kesempatan menaikkan/menurunkan tingkat ancaman |
| `action_ids` dipilih dari `ACTION_CATALOG` (6 id tertutup) | Aksi di luar katalog mustahil tampil; id tak dikenal masuk `dropped_ids` |
| Teks aksi dirender dari katalog, bukan dari model | Wording tidak bisa berhalusinasi |
| Urutan aksi di-*sort* mengikuti prioritas katalog | Evakuasi selalu di atas patroli, apa pun urutan dari model |
| JSON rusak → fallback 2 aksi prioritas tertinggi + `error` flag | Advisory tidak pernah kosong |
| `risk_level` tak dikenal → `MEDIUM` | Tidak pernah diam-diam turun ke `LOW` |

**Verifikasi (live, `qwen3.5:4b-q4_K_M`, seed 42):**

```json
{
  "severity": "HIGH",
  "action_ids": ["EVAC_IMMEDIATE", "FIREBREAK", "AERIAL", "PATROL"],
  "audit": { "prompt_sha": "a5b7295ccafc202b", "dropped_ids": [], "error": null }
}
```

Sebelum perbaikan, model yang sama mengembalikan `CRITICAL` dan "barikade air". Sesudahnya: `HIGH` dan empat aksi katalog. Self-check: 10/10 lulus (`python server/llm_agent/advisory.py`).

Sisa cacat kualitas yang belum ditutup: narasi masih bisa canggung secara bahasa (contoh terukur: *"melewati kontur berkontur curam"*). Ini kosmetik dan tidak mempengaruhi keputusan, jadi dibiarkan sampai model final ditentukan.



* **67 t/s** pada 4B berarti ~300 token advisory selesai dalam **~4,5 s** setelah model termuat. Cold load menambah ~6–7 s.
* **Wall 11,4 s** dengan `keep_alive=0` adalah angka realistis untuk pipeline misi tunggal (satu advisory per penerbangan).
* **Prefill 1100 t/s** berarti prompt 230 token nyaris gratis (~0,2 s). Menambah konteks spasial tidak akan menjadi bottleneck.
* **VRAM 3,97 GB** menyisakan ~3,2 GB untuk NodeODM. Ini mengonfirmasi NFR-RELI-02 bisa dipenuhi **hanya jika** keduanya serial. Kalau dipaksa paralel, 3,97 + 2–4 GB > 7,2 GB usable → OOM.

---

## 7. Rekomendasi

1. **Default produksi: `qwen3.5:4b-q4_K_M`.** Terukur, lolos KPI dengan margin besar, hemat 1,6 GB VRAM dibanding 9B.
2. **`qwen3.5:9b` tetap kandidat**, tetapi hanya jika setelah diunduh terbukti kualitas narasinya jauh lebih baik **dan** tetap > 30 t/s. Jangan menunggu model ini untuk mulai menulis pipeline.
3. **`gemma4:e4b` tidak dipilih** sebagai default: lebih lambat 17%, output lebih panjang (190 vs 152 token), dan tidak ada keunggulan terukur di tugas ini.
4. **Pindahkan `severity` keluar dari LLM** (lihat §5.1). Ini perubahan kontrak data, bukan sekadar prompt.
5. Ulangi benchmark ini setelah `num_ctx` final ditentukan dan setelah NodeODM terpasang, untuk mengukur VRAM gabungan pada urutan nyata (ODM → unload → LLM).

---

## 8. Reproduksi

```powershell
# satu model
python benchmarks\bench_llm.py --repeats 3 qwen3.5:4b-q4_K_M

# semua model di daftar MODELS
python benchmarks\bench_llm.py
```

Hasil mentah (per-run, termasuk output teks lengkap) tersimpan di `benchmarks/results/`.
Jalankan **tanpa** proses `ollama pull` lain yang berjalan bersamaan — kontensi disk menggeser `wall_s` secara signifikan.
