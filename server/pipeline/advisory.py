"""Advisory assembly: engine owns severity, catalog owns wording.

The LLM path is optional. When Ollama is unavailable the template produces the
same contract, so a mission never fails because the model is down.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..llm_agent.advisory import ACTION_CATALOG, generate, severity_from_engine

ACTIONS_BY_SEVERITY = {
    "CRITICAL": ["EVAC_IMMEDIATE", "EVAC_ROUTE", "FIREBREAK", "AERIAL"],
    "HIGH": ["EVAC_IMMEDIATE", "FIREBREAK", "AERIAL", "PATROL"],
    "MEDIUM": ["FIREBREAK", "PATROL", "EARLY_WARNING"],
    "LOW": ["PATROL", "EARLY_WARNING"],
}


def _template(mission_id: str, fusion: dict) -> dict:
    sev = severity_from_engine(fusion)
    ids = ACTIONS_BY_SEVERITY[sev]
    first = (fusion.get("hotspots") or [{}])[0]
    env = fusion.get("environmental_data", {})
    pred = fusion.get("spread_prediction", {})
    rate = float(pred.get("rate_m_min") or 0.0)
    horizon = int(pred.get("estimated_arrival_minutes") or 60)
    bearing = pred.get("bearing_deg")
    narrative = (
        f"Api terdeteksi di {float(first.get('lat', 0)):.5f}, {float(first.get('lon', 0)):.5f} "
        f"pada elevasi {first.get('elevation_m', '—')} m dengan lereng {first.get('slope_deg', '—')}°. "
        f"Angin {env.get('wind_speed_kmh', '—')} km/jam dari {env.get('wind_direction_deg', '—')}°, "
        f"kelembapan {env.get('humidity_pct', '—')}%. Model memperkirakan laju rambat "
        f"{rate:.1f} m/menit" + (f" ke arah {bearing}°" if bearing is not None else "") +
        f", mencapai sekitar {rate * horizon:.0f} m dalam {horizon} menit."
    )
    return {
        "id": f"ADV-{mission_id}",
        "severity": sev,
        "summary_narrative": narrative,
        "action_ids": ids,
        "action_items": [ACTION_CATALOG[i] for i in ids],
        "model": "template",
        "seed": 0,
        "prompt_sha": "template",
        "dropped_ids": [],
        "error": None,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "draft": True,
        "simulated": True,
    }


def build(mission_id: str, fusion: dict, use_llm: bool = False,
          model: str = "qwen3.5:4b-q4_K_M") -> dict:
    if not use_llm:
        return _template(mission_id, fusion)
    try:
        adv = generate(fusion, model)
        d = adv.as_dict()
        return {
            "id": f"ADV-{mission_id}",
            "severity": d["severity"],
            "summary_narrative": d["summary_narrative"],
            "action_ids": d["action_ids"],
            "action_items": d["action_items"],
            "model": d["audit"]["model"],
            "seed": d["audit"]["seed"],
            "prompt_sha": d["audit"]["prompt_sha"],
            "dropped_ids": d["audit"]["dropped_ids"],
            "error": d["audit"]["error"],
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "draft": True,
            "simulated": False,
        }
    except Exception as exc:  # model down must not fail the mission
        out = _template(mission_id, fusion)
        out["error"] = f"llm_unavailable: {exc}"
        return out
