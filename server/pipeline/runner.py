"""Mission orchestration: ODM -> assets -> fusion -> spread -> advisory -> DB."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .. import config, db
from . import advisory as advisory_mod
from . import assets, spread
from . import fusion as fusion_mod
from . import weather as weather_mod
from ..photogrammetry import nodeodm


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalise(spots: list[dict], hm: dict) -> list[dict]:
    out = []
    for i, s in enumerate(spots or [], 1):
        s = dict(s)
        s.setdefault("id", f"SPOT_{i:02d}")
        if "lat" not in s or "lon" not in s:
            u = float(s.get("u", 0.5))
            v = float(s.get("v", 0.5))
            s["lon"] = hm["west"] + (hm["east"] - hm["west"]) * u
            s["lat"] = hm["south"] + (hm["north"] - hm["south"]) * v
        s["fire_confidence"] = s.get("fire_confidence", s.get("confidence", 0.5))
        s["smoke_confidence"] = s.get("smoke_confidence", s.get("smoke", 0.4))
        s["source"] = s.get("source", "MANUAL")
        s["detected_at"] = s.get("detected_at") or _now()
        out.append(s)
    return out


def run_mission(
    photo_dir: str | Path,
    mission_id: str | None = None,
    mode: str = "PRE_FIRE",
    odm_task_dir: str | Path | None = None,
    hotspots: list[dict] | None = None,
    use_llm: bool = False,
    online: bool = False,
    on_update=None,
) -> dict:
    config.ensure_dirs()
    mission_id = mission_id or f"FLIGHT_{datetime.now():%Y%m%d_%H%M%S}"
    out = config.MISSIONS / mission_id
    out.mkdir(parents=True, exist_ok=True)
    photo_dir = Path(photo_dir)

    conn = db.init_db()
    db.upsert_mission(conn, {
        "id": mission_id, "mission_mode": mode, "photo_dir": str(photo_dir),
        "status": "PHOTOGRAMMETRY", "stage": "PHOTOGRAMMETRY",
        "started_at": _now(),
    })

    try:
        if odm_task_dir is None:
            task_dir, odm_uuid = nodeodm.run(photo_dir, out / "odm", config.ODM_OPTIONS, on_update)
        else:
            task_dir = Path(odm_task_dir)
            odm_uuid = task_dir.name

        db.update_mission(conn, mission_id, status="FUSION", stage="FUSION",
                          odm_task_id=odm_uuid)
        a = assets.export_odm_assets(task_dir, out)
        hm = fusion_mod.load_heightmap(a["heightmap_path"])

        if not hotspots:
            hotspots = [{"id": "SPOT_01", "u": 0.5, "v": 0.5,
                         "confidence": 0.5, "smoke": 0.4, "source": "MANUAL"}]
        spots = _normalise(hotspots, hm)
        for s in spots:
            s.update(fusion_mod.sample(hm, s["lat"], s["lon"]))

        center = {"lat": (hm["south"] + hm["north"]) / 2,
                  "lon": (hm["west"] + hm["east"]) / 2}
        weather = weather_mod.get_weather(center["lat"], center["lon"],
                                          online=online, mission_id=mission_id)

        preds: list[dict] = []
        for s in spots:
            preds.extend(spread.predict(s, weather))

        photo_stats = {
            "images_submitted": a.get("images_submitted"),
            "images_aligned": a.get("images_aligned"),
            "align_ratio": a.get("align_ratio"),
            "rmse_reprojection_px": a.get("rmse_reprojection_px"),
            "odm_task_id": odm_uuid,
        }
        mission_row = {
            "id": mission_id, "mission_mode": mode,
            "photos": a.get("images_submitted"), "aligned": a.get("images_aligned"),
            "align_ratio": a.get("align_ratio"), "odm_task_id": odm_uuid,
        }
        fusion_data = fusion_mod.build_fusion(mission_row, hm, spots, weather, preds, photo_stats)
        fusion_path = out / "spatial_fusion.json"
        fusion_mod.write_json(fusion_path, fusion_data)

        db.update_mission(conn, mission_id, status="ADVISORY", stage="ADVISORY",
                          fusion_path=str(fusion_path))
        advisory = advisory_mod.build(mission_id, fusion_data, use_llm=use_llm)
        advisory_path = out / "advisory.json"
        fusion_mod.write_json(advisory_path, advisory)

        db.replace_hotspots(conn, mission_id, spots)
        db.replace_predictions(conn, mission_id, preds)
        db.add_weather(conn, mission_id, weather)
        db.upsert_advisory(conn, mission_id, advisory)

        mesh_path = task_dir / "odm_texturing" / "odm_textured_model_geo.glb"
        dem_path = task_dir / "odm_dem" / "dsm.tif"
        db.update_mission(
            conn, mission_id,
            status="DONE", stage="DONE", ended_at=_now(),
            area_m2=a.get("area_m2") or fusion_data.get("area_coverage_m2"),
            photos=a.get("images_submitted"), aligned=a.get("images_aligned"),
            align_ratio=a.get("align_ratio"), processing_s=a.get("processing_s"),
            gsd_cm=a.get("gsd_cm"),
            dem_path=str(dem_path) if dem_path.exists() else None,
            ortho_path=a["ortho_path"], mesh_path=str(mesh_path) if mesh_path.exists() else None,
            heightmap_path=a["heightmap_path"], fusion_path=str(fusion_path),
            advisory_path=str(advisory_path),
        )
        return db.mission_bundle(conn, mission_id)
    except Exception as exc:
        db.update_mission(conn, mission_id, status="FAILED", stage="FAILED",
                          error_message=str(exc))
        raise

