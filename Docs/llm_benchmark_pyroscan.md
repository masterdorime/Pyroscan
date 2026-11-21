# LLM Benchmark — Ground Station (SPIKE-04 / DG-03)

**Status:** Partial — 2 of 4 candidates measured
**Date:** 2026-11-14
**Hardware:** Lenovo LOQ, RTX 4060 Laptop **8 GB** (8188 MiB), driver 581.86
**Runtime:** Ollama 0.40.5, Python 3.14.7
**Harness:** `benchmarks/bench_llm.py` (stdlib only)

---

## 1. Why this benchmark exists

PRD v1.3.0 §9 DG-03 requires the LLM to be chosen from measurement, not from a table found online. Every number in the earlier PRD was a **third-party estimate**. This document replaces them with numbers from the machine that will actually sit at the command post.

## 2. Method

The workload is exactly what FR-SRV-06 asks for: spatial JSON in → advisory JSON out.

| Parameter | Value |
|---|---|
| `num_ctx` | 8192 (explicit; Ollama defaults to 4K below 24 GiB) |
| `temperature` / `seed` | 0.2 / 42 (deterministic) |
| `format` | `json` (structured output, per contract) |
| `think` | `false` (reasoning traces off) |
| `keep_alive` | `0` → **every run pays a cold load**, as the real pipeline does when it frees VRAM for NodeODM |
| Prompt length | ~230 tokens (14 spatial fields + instructions) |
| Output target | ~150–190 tokens |

**How it is measured:**
* Decode and prefill throughput come from Ollama's own `eval_duration` / `prompt_eval_duration` fields (nanoseconds), not a stopwatch.
* Peak VRAM is sampled by a single long-lived `nvidia-smi --loop-ms=100` process for the duration of the request.
* The model is unloaded (`keep_alive: 0`) before every run so each run measures a cold start.
* GPU placement is read by a separate probe after the trial (`/api/ps` cannot be polled during generation — Ollama serves one request at a time).
* Repeats: 3× for the primary model (median reported), 1× for the comparison model.

---

## 3. Measured results

| Model | Decode (t/s) | Prefill (t/s) | Wall, cold (s) | Output (tok) | VRAM peak | Placement | JSON valid |
|---|---|---|---|---|---|---|---|
| `qwen3.5:4b-q4_K_M` | **67.1** | 1112.5 | **11.4** | 152 | +3.97 GB | 100% GPU | 3/3 |
| `gemma4:e4b` | 55.9 | 895.7 | 16.2 | 190 | +4.41 GB | 100% GPU | 1/1 |

Note: `gemma4:e4b` reports 9.6 GB at pull time, but the build that loads occupies only ~4.4 GB of VRAM and runs 100% on GPU. Download size is not VRAM footprint.

### 3.1. Not measured

| Model | Reason |
|---|---|
| `qwen3.5:9b` (~5.6 GB) | Download stalled at 9% — network at 210–260 KB/s, estimate > 1 hour per model |
| `qwen3-vl:4b` (~3.3 GB) | Same; cancelled so it would not distort the measurement through disk and bandwidth contention |

Partial blobs are retained and the pull can resume at any time. Run:

```powershell
ollama pull qwen3.5:9b
ollama pull qwen3-vl:4b
python benchmarks\bench_llm.py --repeats 3 qwen3.5:9b qwen3-vl:4b
```

---

## 4. Check against the PRD §7 KPIs

| KPI | Target | Measured | Status |
|---|---|---|---|
| Advisory latency (ODM DONE → advisory stored) | < 90 s | **11.4 s** (including cold load) | ✅ passes by 7.9× |
| JSON contract quality | parses + 3 keys + ≥3 action items | 3/3 runs | ✅ passes |

**The important conclusion:** the 4B model already clears the latency KPI by a wide margin. The 9B model is not required for the system to work — it is a quality upgrade, not a necessity. That lowers the urgency of the 5.6 GB download.

---

## 5. Quality findings (more important than throughput)

Both models produce reasonable Indonesian and valid JSON. But two problems must be handled in code, not in the document:

### 5.1. The LLM changed the severity the engine supplied

The input states `risk_level: HIGH` from the simulation engine. Output:

| Model | `severity` returned |
|---|---|
| `qwen3.5:4b-q4_K_M` | **CRITICAL** ← escalated one level |
| `gemma4:e4b` | HIGH |

**Recommendation:** `severity` must **not** be produced by the LLM. It comes from the deterministic simulation engine; the LLM writes only `summary_narrative` and `action_items`. Otherwise two missions with identical data can report different threat levels — unacceptable for an evacuation decision.

### 5.2. Some actions were technically nonsensical

`qwen3.5:4b-q4_K_M` produced *"Tim SAR membentuk barikade air di jalur prediksi"* — a water barricade does not stop a forest fire; this is a domain hallucination. `gemma4:e4b` wrote *"jalur evakuasi alternatif yang menjauhi arah angin (barat daya ke timur laut)"* — the direction it names is the direction the fire **spreads**, not a direction away from it.

**Recommendation:**
1. `action_items` is restricted to a closed action vocabulary (evacuation, firebreak, route, coordination) via an enumerated prompt plus post-generation validation.
2. Every advisory carries a disclaimer and a "draft — verify in the field" label in the dashboard. The LLM must never be the only source of a SAR recommendation.
3. Store `prompt_sha` + `model` + `seed` in the advisory table for audit.

---

## 6. Performance interpretation

* **67 t/s** on a 4B model means a ~300-token advisory completes in **~4.5 s** once loaded. Cold load adds ~6–7 s.
* **Wall 11.4 s** with `keep_alive=0` is the realistic figure for a single-mission pipeline (one advisory per flight).
* **Prefill at 1100 t/s** makes a 230-token prompt essentially free (~0.2 s). Adding spatial context will not become the bottleneck.
* **3.97 GB VRAM** leaves ~3.2 GB for NodeODM. This confirms NFR-RELI-02 can only be met **if** the two run in sequence. Forced parallel: 3.97 + 2–4 GB > 7.2 GB usable → OOM.

---

## 7. Recommendations

1. **Production default: `qwen3.5:4b-q4_K_M`.** Measured, clears the KPI by a wide margin, saves 1.6 GB of VRAM versus the 9B.
2. **`qwen3.5:9b` stays a candidate**, but only if after downloading it proves clearly better at narrative while holding > 30 t/s. Do not wait for it to start writing the pipeline.
3. **`gemma4:e4b` is not selected:** 17% slower, longer output (190 vs 152 tokens), and no measured advantage on this task.
4. **Move `severity` out of the LLM** (see §5.1). This is a data-contract change, not just a prompt tweak.
5. Re-run this benchmark once the final `num_ctx` is settled and NodeODM is installed, to measure combined VRAM on the real sequence (ODM → unload → LLM).

---

## 8. Reproducing

```powershell
# one model
python benchmarks\bench_llm.py --repeats 3 qwen3.5:4b-q4_K_M

# every model in the MODELS list
python benchmarks\bench_llm.py
```

Raw results (per run, including the full output text) are written to `benchmarks/results/`.
Run it **without** another `ollama pull` in flight — disk contention shifts `wall_s` significantly.
