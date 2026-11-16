"""Runnable self-check for the pipeline core. No frameworks."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .pipeline import advisory, fusion, spread


def main() -> int:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    tmp = Path(tempfile.mkdtemp()) / "selftest.db"
    conn = db.init_db(tmp)

    W = H = 16
    heights = [700 + c * 8.0 for r in range(H) for c in range(W)]
    hm = {
        "width": W, "height": H,
        "west": 107.600, "east": 107.601,
        "south": -6.920, "north": -6.919,
        "height_scale_m": 1.0, "geoid_offset_m": 0.0, "base_height_m": 0.0,
        "h_min": 700.0, "h_max": 820.0, "heights_m": heights,
    }
    lat, lon = -6.9195, 107.6005
    p = fusion.sample(hm, lat, lon)
    assert 35 <= p["slope_deg"] <= 60, p
    assert 250 <= p["aspect_deg"] <= 290, p

    hots = [{
        "id": "SPOT_01", "lat": lat, "lon": lon,
        "fire_confidence": 0.9, "smoke_confidence": 0.8,
        "source": "MANUAL", "detected_at": now,
        **p,
    }]
    weather = {
        "wind_speed_kmh": 24.5, "wind_dir_deg": 225.0, "humidity_pct": 38,
        "temperature_c": 31.2, "source": "fixture", "observed_at": now,
        "is_cached": 1, "age_min": 5,
    }
    preds = spread.predict(hots[0], weather)
    assert {x["horizon_min"] for x in preds} == {30, 60}
    assert preds[-1]["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    mission = {"id": "T1", "mission_mode": "PRE_FIRE", "photos": 18, "aligned": 18,
               "align_ratio": 1.0, "odm_task_id": "test"}
    fusion_data = fusion.build_fusion(mission, hm, hots, weather, preds)
    assert fusion_data["spread_prediction"]["risk_level"] == preds[-1]["risk_level"]
    assert fusion_data["hotspots"][0]["elevation_m"] > 700

    adv = advisory.build("T1", fusion_data, use_llm=False)
    assert adv["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert len(adv["action_items"]) >= 2

    db.upsert_mission(conn, {"id": "T1", "mission_mode": "PRE_FIRE",
                             "photo_dir": "fixtures", "status": "DONE",
                             "stage": "DONE", "started_at": now})
    db.replace_hotspots(conn, "T1", hots)
    db.replace_predictions(conn, "T1", preds)
    db.add_weather(conn, "T1", weather)
    db.upsert_advisory(conn, "T1", adv)
    bundle = db.mission_bundle(conn, "T1")
    assert bundle["mission"]["id"] == "T1"
    assert len(bundle["hotspots"]) == 1
    assert len(bundle["predictions"]) == 2
    assert bundle["advisory"]["severity"] == adv["severity"]

    print("PASS selftest: fusion, spread, advisory, db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
