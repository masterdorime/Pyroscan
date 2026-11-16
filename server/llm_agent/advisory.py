#!/usr/bin/env python3
"""PyroScan offline advisory generator (FR-SRV-06).

The LLM writes prose. It does not decide anything.

Two failures were measured on real hardware (see Docs/llm_benchmark_pyroscan.md):

  1. qwen3.5:4b turned the engine's risk_level HIGH into severity CRITICAL.
     Two missions with identical data would produce different threat levels.
  2. It invented "barikade air" (a water barricade) as a firefighting action.

Both are prompt-proofing problems, so neither is fixed with prompt wording here:

  * severity is taken from the simulation engine and never sent to the model
  * action_items are chosen from a closed catalog by id; anything else is dropped

Stdlib only. Requires Ollama on 127.0.0.1:11434 for --live.

    python server/llm_agent/advisory.py                        # self-check
    python server/llm_agent/advisory.py --live qwen3.5:4b-q4_K_M
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

OLLAMA = "http://127.0.0.1:11434"
NUM_CTX = 8192
SEED = 42
MAX_ACTIONS = 4

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

# Closed vocabulary. The model may only return these ids; the operator reads
# the Indonesian phrasing from here, so wording is never model-generated
# either. Adding an action is a deliberate edit to this table.
ACTION_CATALOG: dict[str, str] = {
    "EVAC_IMMEDIATE": "Evakuasi segera warga pada sektor yang dilalui arah rambat api.",
    "EVAC_ROUTE": "Aktifkan rute evakuasi alternatif yang menjauhi arah rambat, bukan mengikuti arah angin.",
    "FIREBREAK": "Bangun firebreak/sekat bakar pada kontur yang ditentukan di depan lidah api.",
    "AERIAL": "Ajukan pemadaman udara (water bombing) pada koordinat prediksi.",
    "PATROL": "Tingkatkan patroli dan pemantauan hotspot di sepanjang jalur prediksi.",
    "EARLY_WARNING": "Aktifkan peringatan dini dan koordinasi lintas instansi.",
}


@dataclass
class Advisory:
    severity: str
    summary_narrative: str
    action_items: list[str]
    action_ids: list[str]
    model: str
    seed: int
    prompt_sha: str
    dropped_ids: list[str] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "severity": self.severity,
            "summary_narrative": self.summary_narrative,
            "action_items": self.action_items,
            "action_ids": self.action_ids,
            "audit": {
                "model": self.model,
                "seed": self.seed,
                "prompt_sha": self.prompt_sha,
                "dropped_ids": self.dropped_ids,
                "error": self.error,
            },
        }


def severity_from_engine(fusion: dict) -> str:
    """The simulation engine owns this value. We only validate it.

    Per data_contracts §2, risk_level lives inside spread_prediction. The
    top-level form is accepted for MODE-B missions and fixtures that carry no
    prediction at all.
    """
    pred = fusion.get("spread_prediction") or {}
    value = str(pred.get("risk_level") or fusion.get("risk_level") or "").upper()
    if value not in SEVERITIES:
        # ponytail: unknown -> MEDIUM, not silent LOW. Under-alerting is the
        # failure mode that gets people hurt.
        return "MEDIUM"
    return value


def build_prompt(fusion: dict) -> str:
    spots = fusion.get("hotspots", [])
    env = fusion.get("environmental_data", {})
    pred = fusion.get("spread_prediction", {})
    first = spots[0] if spots else {}

    catalog = "\n".join(f"- {k}: {v}" for k, v in ACTION_CATALOG.items())
    return f"""Anda adalah analis kebakaran hutan. Tulis ringkasan situasi untuk komando SAR.

DATA SPASIAL:
- Hotspot: {len(spots)} titik
- Titik utama: lat {first.get('lat')}, lon {first.get('lon')}
- Elevasi: {first.get('elevation_m')} m, kelandaian {first.get('slope_deg')} derajat, aspect {first.get('aspect_deg')} derajat
- Kepercayaan api: {first.get('fire_confidence')}, asap: {first.get('smoke_confidence')}
- Angin: {env.get('wind_speed_kmh')} km/jam, arah {env.get('wind_direction_deg')} derajat
- Kelembapan: {env.get('humidity_pct')} persen, suhu: {env.get('temperature_c')} celsius
- Prediksi: lat {pred.get('predicted_lat')}, lon {pred.get('predicted_lon')}, dalam {pred.get('estimated_arrival_minutes')} menit

PILIH TINDAKAN DARI DAFTAR BERIKUT SAJA (gunakan id-nya):
{catalog}

Balas HANYA objek JSON:
- "summary_narrative": 2-3 kalimat bahasa Indonesia tentang arah rambat api
- "action_ids": array 2-{MAX_ACTIONS} id dari daftar di atas, urut prioritas

Jangan menulis tingkat ancaman. Jangan mengarang tindakan di luar daftar."""


def _render(ids: list[str]) -> list[str]:
    return [ACTION_CATALOG[i] for i in ids]


def _fallback_ids() -> list[str]:
    """Catalog order is priority order: evakuasi before patroli."""
    return list(ACTION_CATALOG)[:2]


def parse_advisory(
    raw: str, fusion: dict, model: str, prompt_sha: str, seed: int = SEED
) -> Advisory:
    """Turn model output into an advisory. Never trusts it for severity or actions."""
    severity = severity_from_engine(fusion)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return Advisory(
            severity=severity,
            summary_narrative="",
            action_items=_render(_fallback_ids()),
            action_ids=_fallback_ids(),
            model=model,
            seed=seed,
            prompt_sha=prompt_sha,
            error="unparseable_json",
        )

    narrative = obj.get("summary_narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        narrative = ""

    requested = obj.get("action_ids")
    if not isinstance(requested, list):
        requested = []

    kept: list[str] = []
    dropped: list[str] = []
    for item in requested:
        if not isinstance(item, str):
            dropped.append(str(item))
        elif item in ACTION_CATALOG:
            if item not in kept:
                kept.append(item)
        else:
            dropped.append(item)

    if not kept:
        # Never ship an advisory with zero actions: fall back to catalog order,
        # which is already priority-ordered by domain.
        kept = _fallback_ids()
    else:
        # Model ordering is a judgement we do not need to inherit: evakuasi must
        # outrank patroli even if the model lists them the other way round.
        kept.sort(key=list(ACTION_CATALOG).index)

    return Advisory(
        severity=severity,
        summary_narrative=narrative.strip(),
        action_items=_render(kept[:MAX_ACTIONS]),
        action_ids=kept[:MAX_ACTIONS],
        model=model,
        seed=seed,
        prompt_sha=prompt_sha,
        dropped_ids=dropped,
    )


def generate(
    fusion: dict, model: str, host: str = OLLAMA, timeout: int = 300
) -> Advisory:
    prompt = build_prompt(fusion)
    prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()[:16]
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "keep_alive": 0,
        "options": {"num_ctx": NUM_CTX, "temperature": 0.2, "seed": SEED},
    }
    try:
        payload["think"] = False
        raw = _post(host, payload, timeout)["response"]
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise
        payload.pop("think", None)
        raw = _post(host, payload, timeout)["response"]
    return parse_advisory(raw, fusion, model, prompt_sha)


def _post(host: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        host + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


FIXTURE = {
    "risk_level": "HIGH",
    "hotspots": [
        {
            "lat": -6.9175,
            "lon": 107.6191,
            "elevation_m": 750.5,
            "slope_deg": 32.4,
            "aspect_deg": 45.0,
            "fire_confidence": 0.92,
            "smoke_confidence": 0.85,
        }
    ],
    "environmental_data": {
        "wind_speed_kmh": 24.5,
        "wind_direction_deg": 225.0,
        "humidity_pct": 38,
        "temperature_c": 31.2,
    },
    "spread_prediction": {
        "predicted_lat": -6.9120,
        "predicted_lon": 107.6250,
        "estimated_arrival_minutes": 45,
        "risk_level": "HIGH",
    },
}


def demo() -> int:
    """Regression check for the two failures observed in the benchmark."""
    failures = 0

    def check(label: str, cond: bool) -> None:
        nonlocal failures
        print(f"  {'ok  ' if cond else 'FAIL'} {label}")
        if not cond:
            failures += 1

    print("self-check")

    # The exact output qwen3.5:4b produced in the benchmark: escalated severity
    # and an invented "barikade air" action.
    hostile = json.dumps(
        {
            "severity": "CRITICAL",
            "summary_narrative": "Api bergerak cepat ke timur laut.",
            "action_ids": ["EVAC_IMMEDIATE", "WATER_BARRICADE"],
            "action_items": ["Tim SAR membentuk barikade air di jalur prediksi."],
        }
    )
    adv = parse_advisory(hostile, FIXTURE, "fake", "deadbeef")

    check("severity stays HIGH (engine), not CRITICAL (model)", adv.severity == "HIGH")
    check("invented action id dropped", adv.dropped_ids == ["WATER_BARRICADE"])
    check("no water barricade in output", not any("barikade" in a for a in adv.action_items))
    check("kept action rendered from catalog", adv.action_items[0] == ACTION_CATALOG["EVAC_IMMEDIATE"])

    # Free-text action_items from the model are ignored entirely.
    free_text = json.dumps({"summary_narrative": "x", "action_items": ["barikade air"]})
    adv2 = parse_advisory(free_text, FIXTURE, "fake", "deadbeef")
    check("free-text actions ignored", adv2.action_ids == ["EVAC_IMMEDIATE", "EVAC_ROUTE"])

    # Garbage and empty responses still yield a usable, safe advisory.
    adv3 = parse_advisory("not json at all", FIXTURE, "fake", "deadbeef")
    check("unparseable flagged", adv3.error == "unparseable_json")
    check("unparseable still has actions", len(adv3.action_ids) >= 2)
    check("unparseable still has engine severity", adv3.severity == "HIGH")

    # Unknown engine severity must not silently downgrade to LOW.
    adv4 = parse_advisory("{}", {"risk_level": "WAT"}, "fake", "x")
    check("unknown severity -> MEDIUM", adv4.severity == "MEDIUM")

    # risk_level inside spread_prediction (the documented location) must win
    # over a stale top-level copy.
    nested = {
        "risk_level": "LOW",
        "spread_prediction": {"risk_level": "CRITICAL"},
    }
    check("nested risk_level wins", severity_from_engine(nested) == "CRITICAL")
    check("MODE-B falls back to top-level", severity_from_engine({"risk_level": "HIGH"}) == "HIGH")

    # Duplicates collapse; catalog cap respected.
    dupes = json.dumps({"summary_narrative": "x", "action_ids": ["PATROL"] * 5 + list(ACTION_CATALOG)})
    adv5 = parse_advisory(dupes, FIXTURE, "fake", "x")
    check("deduped and capped", adv5.action_ids == list(ACTION_CATALOG)[:MAX_ACTIONS])

    print(f"\n{'PASS' if failures == 0 else 'FAILED'} ({failures} failure(s))")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", metavar="MODEL", help="call Ollama and print a real advisory")
    args = ap.parse_args()

    rc = demo()
    if args.live:
        print(f"\nlive: {args.live}")
        adv = generate(FIXTURE, args.live)
        print(json.dumps(adv.as_dict(), indent=2, ensure_ascii=False))
        if adv.error:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
