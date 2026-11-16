"""FastAPI: REST + SSE + the dashboard static shell."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .llm_agent.advisory import ACTION_CATALOG
from .pipeline import fusion as fusion_mod
from .pipeline import weather as weather_mod

app = FastAPI(title="PyroScan", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _conn():
    return db.init_db()


def _hm(mission: dict) -> dict | None:
    p = mission.get("heightmap_path")
    if p and Path(p).exists():
        return fusion_mod.load_heightmap(p)
    fallback = config.WEB / "data" / "heightmap.json"
    return fusion_mod.load_heightmap(fallback) if fallback.exists() else None


def _uv(hm: dict | None, lat: float, lon: float) -> tuple[float, float]:
    if not hm:
        return 0.5, 0.5
    u = (lon - hm["west"]) / max(hm["east"] - hm["west"], 1e-12)
    v = (lat - hm["south"]) / max(hm["north"] - hm["south"], 1e-12)
    return round(min(1, max(0, u)), 4), round(min(1, max(0, v)), 4)


def _age(iso: str | None) -> int:
    if not iso:
        return 0
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds() / 60))
    except Exception:
        return 0


def _advisory(bundle: dict) -> dict | None:
    a = bundle.get("advisory")
    if not a:
        return None
    try:
        ids = json.loads(a.get("action_ids_json") or "[]")
    except Exception:
        ids = []
    actions = [ACTION_CATALOG[i] for i in ids if i in ACTION_CATALOG]
    return {
        "severity": a["severity"],
        "summary": a.get("narrative") or "",
        "actions": actions,
        "action_ids": ids,
        "model": a.get("model"),
        "seed": a.get("seed"),
        "prompt_sha": a.get("prompt_sha"),
        "draft": True,
        "simulated": a.get("model") == "template",
        "error": a.get("error"),
    }


def _weather(bundle: dict, hm: dict | None) -> dict:
    w = bundle.get("weather")
    if not w and hm:
        w = weather_mod.get_weather((hm["south"] + hm["north"]) / 2,
                                    (hm["west"] + hm["east"]) / 2)
    w = w or {}
    source = w.get("source") or "unknown"
    return {
        "wind_speed_kmh": w.get("wind_speed_kmh"),
        "wind_dir_deg": w.get("wind_dir_deg"),
        "temp_c": w.get("temperature_c"),
        "humidity_pct": w.get("humidity_pct"),
        "source": source,
        "age_min": _age(w.get("observed_at")),
        "simulated": "fixture" in source.lower(),
    }


def _prediction(bundle: dict) -> dict:
    preds = bundle.get("predictions") or []
    w = bundle.get("weather") or {}
    wind_to = ((float(w.get("wind_dir_deg") or 0)) + 180.0) % 360.0
    rate60 = max((p.get("rate_m_min") or 0 for p in preds if p.get("horizon_min") == 60), default=0)
    area60 = round(0.71 + rate60 * 0.09, 2)
    area30 = round(0.71 + rate60 * 0.045, 2)
    steps = [
        {"min": 0, "area_ha": 0.71, "rate_m_min": 0},
        {"min": 30, "area_ha": area30, "rate_m_min": round(rate60 * 0.75, 1)},
        {"min": 60, "area_ha": area60, "rate_m_min": round(rate60, 1)},
    ]
    chart_area = [round(0.71 + (area60 - 0.71) * (i / 11) ** 1.2, 2) for i in range(12)]
    chart_rate = [round(rate60 * (i / 11) ** 0.8, 1) for i in range(12)]

    fx_path = config.WEB / "data" / "fixtures.json"
    events = []
    if fx_path.exists():
        fx = json.loads(fx_path.read_text(encoding="utf-8"))
        if fx.get("mission", {}).get("id") == bundle["mission"]["id"]:
            events = fx["prediction"]["key_events"]
    if not events:
        m = bundle["mission"]
        events = [
            {"time": (m.get("started_at") or "")[11:16], "label": "Mission start", "tone": "muted"},
            {"time": (m.get("ended_at") or "")[11:16], "label": "Advisory drafted", "tone": "amber"},
        ]
    return {"wind_to_deg": wind_to, "steps": steps,
            "chart_area": chart_area, "chart_rate": chart_rate,
            "key_events": events}


def _payload(mission: dict) -> dict:
    conn = _conn()
    bundle = db.mission_bundle(conn, mission["id"])
    hm = _hm(mission)
    spots = []
    for s in bundle["hotspots"]:
        u, v = _uv(hm, s["lat"], s["lon"])
        spots.append({
            "id": s["id"], "u": u, "v": v,
            "confidence": s.get("fire_confidence") or 0.0,
            "smoke": s.get("smoke_confidence") or 0.0,
            "slope_deg": s.get("slope_deg"),
            "age_min": _age(s.get("detected_at")),
        })
    return {
        "mission": {
            "id": mission["id"],
            "mode": mission["mission_mode"],
            "status": mission["status"],
            "area_m2": mission.get("area_m2"),
            "photos": mission.get("photos"),
            "aligned": mission.get("aligned"),
            "align_ratio": mission.get("align_ratio"),
            "processing_s": mission.get("processing_s"),
            "gsd_cm": mission.get("gsd_cm"),
            "started_at": mission.get("started_at"),
            "ended_at": mission.get("ended_at"),
            "stage": mission.get("stage") or mission["status"],
            "stages": config.STAGES,
        },
        "context": config.CONTEXT,
        "weather": _weather(bundle, hm),
        "advisory": _advisory(bundle),
        "hotspots": spots,
        "prediction": _prediction(bundle),
        "flight_path": config.FLIGHT_PATH,
        "assets": {
            "heightmap": f"/api/v1/missions/{mission['id']}/heightmap"
            if mission.get("heightmap_path") else "/data/heightmap.json",
            "ortho": f"/api/v1/missions/{mission['id']}/ortho.webp"
            if mission.get("ortho_path") else "/data/ortho.webp",
            "ortho_shaded": f"/api/v1/missions/{mission['id']}/ortho_shaded.webp"
            if mission.get("ortho_path") and
            (Path(mission["ortho_path"]).parent / "ortho_shaded.webp").exists()
            else "/data/ortho_shaded.webp",
        },
    }


@app.get("/api/v1/health")
def health():
    db_ok = True
    try:
        _conn().execute("SELECT 1").fetchone()
    except Exception:
        db_ok = False
    node = False
    try:
        node = requests.get(f"{config.NODEODM}/info", timeout=1).ok
    except Exception:
        pass
    ollama = False
    try:
        ollama = requests.get("http://127.0.0.1:11434/api/tags", timeout=1).ok
    except Exception:
        pass
    return {"status": "ok", "db": db_ok, "nodeodm": node, "ollama": ollama}


@app.get("/api/v1/missions")
def missions():
    return db.list_missions(_conn())


@app.get("/api/v1/missions/latest")
def latest_mission():
    m = db.latest_mission(_conn())
    if not m:
        raise HTTPException(404, "no missions")
    return _payload(m)


@app.get("/api/v1/missions/{mission_id}")
def mission(mission_id: str):
    m = db.get_mission(_conn(), mission_id)
    if not m:
        raise HTTPException(404, "mission not found")
    return _payload(m)


@app.get("/api/v1/missions/{mission_id}/fusion")
def mission_fusion(mission_id: str):
    m = db.get_mission(_conn(), mission_id)
    if not m or not m.get("fusion_path"):
        raise HTTPException(404, "fusion not found")
    return FileResponse(m["fusion_path"], media_type="application/json")


@app.get("/api/v1/missions/{mission_id}/advisory")
def mission_advisory(mission_id: str):
    bundle = db.mission_bundle(_conn(), mission_id)
    a = _advisory(bundle) if bundle else None
    if not a:
        raise HTTPException(404, "advisory not found")
    return a


@app.get("/api/v1/missions/{mission_id}/heightmap")
def mission_heightmap(mission_id: str):
    m = db.get_mission(_conn(), mission_id)
    if not m or not m.get("heightmap_path"):
        raise HTTPException(404, "heightmap not found")
    return FileResponse(m["heightmap_path"], media_type="application/json")


@app.get("/api/v1/missions/{mission_id}/ortho.webp")
def mission_ortho(mission_id: str):
    m = db.get_mission(_conn(), mission_id)
    if not m or not m.get("ortho_path") or not Path(m["ortho_path"]).exists():
        raise HTTPException(404, "orthophoto not found")
    return FileResponse(m["ortho_path"], media_type="image/webp")


@app.get("/api/v1/missions/{mission_id}/ortho_shaded.webp")
def mission_ortho_shaded(mission_id: str):
    m = db.get_mission(_conn(), mission_id)
    if not m or not m.get("ortho_path"):
        raise HTTPException(404, "orthophoto not found")
    p = Path(m["ortho_path"]).parent / "ortho_shaded.webp"
    if not p.exists():
        raise HTTPException(404, "shaded orthophoto not found")
    return FileResponse(p, media_type="image/webp")


@app.get("/api/v1/missions/{mission_id}/mesh.glb")
def mission_mesh(mission_id: str):
    m = db.get_mission(_conn(), mission_id)
    if not m or not m.get("mesh_path") or not Path(m["mesh_path"]).exists():
        raise HTTPException(404, "mesh not found")
    return FileResponse(m["mesh_path"], media_type="model/gltf-binary")


@app.get("/api/v1/events")
async def events():
    async def stream():
        while True:
            yield "event: heartbeat\ndata: {}\n\n"
            await asyncio.sleep(15)
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


app.mount("/data", StaticFiles(directory=str(config.WEB / "data")), name="data")


@app.get("/")
def index():
    return FileResponse(config.WEB / "dashboard.html")


app.mount("/", StaticFiles(directory=str(config.WEB), html=True), name="web")

