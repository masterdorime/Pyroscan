#!/usr/bin/env python3
"""PyroScan LLM benchmark on the ground-station laptop.

Measures what the PRD actually cares about:
  * decode throughput (tokens/s)
  * prefill / prompt-eval throughput
  * cold load time
  * peak VRAM and whether the model stayed fully on GPU
  * wall time to a complete advisory
  * whether the output parses as the contract JSON

Usage:
    python bench_llm.py                              # all models in MODELS
    python bench_llm.py qwen3.5:4b-q4_K_M            # one model
    python bench_llm.py --repeats 5 qwen3.5:9b

Stdlib only. No pip install. Requires Ollama on 127.0.0.1:11434.

ponytail: subprocess-per-VRAM-sample instead of NVML; 100 ms resolution is
plenty for a 60 s generational peak. Swap to pynvml only if sampling overhead
ever shows up in the numbers.
"""

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434"
NUM_CTX = 8192
REPEATS = 3
RESULTS = Path(__file__).parent / "results"

MODELS = [
    "qwen3.5:9b",
    "qwen3.5:4b-q4_K_M",
    "qwen3-vl:4b",
    "gemma4:e4b",
]

# The real workload from FR-SRV-06: spatial JSON in, advisory JSON out.
PROMPT = """Analisis data spasial kebakaran hutan berikut dan hasilkan laporan komando.

DATA SPASIAL:
- Hotspot: lat -6.9175, lon 107.6191
- Elevasi: 750 m
- Kelandaian lereng: 32 derajat
- Arah lereng (aspect): 45 derajat (timur laut)
- Kepercayaan deteksi api: 0.92
- Kepercayaan deteksi asap: 0.85
- Kecepatan angin: 24.5 km/jam
- Arah angin: dari barat daya ke timur laut
- Kelembapan: 38 persen
- Suhu: 31.2 celsius
- Prediksi 45 menit ke depan: lat -6.9120, lon 107.6250
- Tingkat risiko model: HIGH

Balas HANYA dengan objek JSON dengan kunci berikut:
- "severity": salah satu dari "LOW", "MEDIUM", "HIGH", "CRITICAL"
- "summary_narrative": 2-3 kalimat bahasa Indonesia yang menjelaskan arah rambat api
- "action_items": array 3 string berisi tindakan evakuasi konkret untuk tim SAR

Jangan menulis penjelasan di luar JSON."""


def http_post(path: str, payload: dict, timeout: int = 900) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        OLLAMA + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def http_get(path: str, timeout: int = 60) -> dict:
    with urllib.request.urlopen(OLLAMA + path, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def vram_used_mib() -> int:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    return int(out.splitlines()[0])


def gpu_placement(model: str) -> str:
    """Ollama reports e.g. '100% GPU' or '23%/77% CPU/GPU'."""
    try:
        for m in http_get("/api/ps").get("models", []):
            if m.get("name") == model or m.get("model") == model:
                size = m.get("size", 0) or 1
                on_gpu = m.get("size_vram", 0)
                pct = round(100 * on_gpu / size)
                return f"{pct}% GPU" if pct == 100 else f"{pct}% GPU (spilled to CPU)"
    except (urllib.error.URLError, TimeoutError):
        pass
    return "unknown"


class VramSampler(threading.Thread):
    """One long-lived nvidia-smi --loop-ms process, not one spawn per sample.

    Spawning every 100 ms exhausts Windows handle/memory resources under load
    (WinError 8) and the fork cost pollutes the very timing we measure.
    """

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak = 0
        self.stop = threading.Event()
        self.proc: subprocess.Popen | None = None

    def run(self) -> None:
        try:
            self.proc = subprocess.Popen(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                    "--loop-ms=100",
                ],
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError:
            return
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            if self.stop.is_set():
                break
            for chunk in raw.replace("\r", "\n").split():
                if chunk.isdigit():
                    self.peak = max(self.peak, int(chunk))

    def stop_sampling(self) -> None:
        self.stop.set()
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()


def probe_placement(model: str, baseline: int) -> str:
    """Load the model with a 1-token prompt, read /api/ps, then unload.

    Ollama serves one request at a time, so /api/ps cannot be polled while a
    generation is in flight — it just blocks until the generation ends, by
    which point keep_alive=0 has already evicted the weights.
    """
    try:
        http_post(
            "/api/generate",
            {
                "model": model,
                "prompt": "hi",
                "stream": False,
                "keep_alive": "1m",
                "options": {"num_predict": 1, "num_ctx": NUM_CTX},
            },
        )
        placement = gpu_placement(model)
    except (urllib.error.URLError, TimeoutError):
        placement = "unknown"
    finally:
        unload(model, baseline)
    return placement


def unload(model: str, baseline: int) -> None:
    """Free VRAM so each trial measures a cold load and a clean peak."""
    try:
        http_post("/api/generate", {"model": model, "keep_alive": 0, "prompt": ""})
    except urllib.error.HTTPError:
        pass
    for _ in range(60):
        try:
            if vram_used_mib() <= baseline + 300:
                return
        except (OSError, ValueError, IndexError):
            pass
        time.sleep(0.5)


def trial(model: str, baseline: int) -> dict:
    unload(model, baseline)
    sampler = VramSampler()
    sampler.start()
    t0 = time.perf_counter()
    payload = {
        "model": model,
        "prompt": PROMPT,
        "stream": False,
        "format": "json",
        "keep_alive": 0,
        "options": {"num_ctx": NUM_CTX, "temperature": 0.2, "seed": 42},
    }
    try:
        try:
            # Production config per FR-SRV-06: no reasoning traces, they only
            # add latency to a 300-token advisory.
            r = http_post("/api/generate", {**payload, "think": False})
        except urllib.error.HTTPError as exc:
            if exc.code != 400:
                raise
            r = http_post("/api/generate", payload)
    finally:
        wall = time.perf_counter() - t0
        sampler.stop_sampling()
        sampler.join(timeout=2)
    return {
        "resp": r,
        "wall": wall,
        "peak": sampler.peak,
    }


def score(model: str, runs: list[dict], baseline: int) -> dict:
    def med(fn):
        return statistics.median(fn(r) for r in runs)

    decode = med(
        lambda r: r["resp"]["eval_count"] / (r["resp"]["eval_duration"] / 1e9)
        if r["resp"].get("eval_duration")
        else 0
    )
    prefill = med(
        lambda r: r["resp"]["prompt_eval_count"] / (r["resp"]["prompt_eval_duration"] / 1e9)
        if r["resp"].get("prompt_eval_duration")
        else 0
    )
    load = med(lambda r: r["resp"].get("load_duration", 0) / 1e9)
    wall = med(lambda r: r["wall"])
    peak = max(r["peak"] for r in runs) - baseline
    out_tokens = med(lambda r: r["resp"].get("eval_count", 0))

    checks = []
    for r in runs:
        raw = r["resp"].get("response", "")
        try:
            obj = json.loads(raw)
            ok = (
                isinstance(obj.get("severity"), str)
                and isinstance(obj.get("summary_narrative"), str)
                and isinstance(obj.get("action_items"), list)
                and len(obj.get("action_items", [])) >= 3
            )
            checks.append("ok" if ok else "keys")
        except json.JSONDecodeError:
            checks.append("unparseable")

    return {
        "model": model,
        "placement": "unknown",
        "decode_tps": round(decode, 1),
        "prefill_tps": round(prefill, 1),
        "load_s": round(load, 2),
        "wall_s": round(wall, 1),
        "out_tokens": int(out_tokens),
        "vram_peak_mib": peak,
        "json": checks,
        "sample": runs[-1]["resp"].get("response", ""),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", default=None)
    ap.add_argument("--repeats", type=int, default=REPEATS)
    args = ap.parse_args()
    models = args.models or MODELS

    RESULTS.mkdir(exist_ok=True)
    baseline = vram_used_mib()
    print(f"baseline VRAM: {baseline} MiB   num_ctx={NUM_CTX}   repeats={args.repeats}")
    print(f"available: {[m['name'] for m in http_get('/api/tags')['models']]}\n")

    results = []
    for model in models:
        print(f"=== {model} ===")
        runs = []
        for i in range(args.repeats):
            try:
                runs.append(trial(model, baseline))
                print(f"  run {i + 1}/{args.repeats}: ok")
            except (urllib.error.URLError, TimeoutError, KeyError) as exc:
                print(f"  run {i + 1}/{args.repeats}: FAILED {exc}")
        if not runs:
            print("  skipped (no successful runs)\n")
            continue
        s = score(model, runs, baseline)
        s["placement"] = probe_placement(model, baseline)
        results.append(s)
        (RESULTS / f"{model.replace(':', '_')}.json").write_text(
            json.dumps({"summary": s, "raw": runs}, indent=2), encoding="utf-8"
        )
        print(
            f"  decode {s['decode_tps']} t/s | prefill {s['prefill_tps']} t/s | "
            f"wall {s['wall_s']}s | vram +{s['vram_peak_mib']} MiB | {s['placement']}"
        )
        print(f"  json {s['json']}\n")

    if results:
        (RESULTS / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print("| model | decode t/s | prefill t/s | wall s | out tok | VRAM +MiB | placement | JSON |")
        print("|---|---|---|---|---|---|---|---|")
        for s in results:
            print(
                f"| `{s['model']}` | {s['decode_tps']} | {s['prefill_tps']} | "
                f"{s['wall_s']} | {s['out_tokens']} | {s['vram_peak_mib']} | "
                f"{s['placement']} | {','.join(s['json'])} |"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
