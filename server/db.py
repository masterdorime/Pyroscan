"""SQLite persistence for PyroScan. Schema follows Docs/data_contracts §5."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import config

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS mission (
  id            TEXT PRIMARY KEY,
  mission_mode  TEXT NOT NULL CHECK (mission_mode IN ('PRE_FIRE','BURN_SCAR')),
  started_at    TEXT NOT NULL,
  ended_at      TEXT,
  area_m2       REAL,
  status        TEXT NOT NULL DEFAULT 'CAPTURING'
                CHECK (status IN ('CAPTURING','PHOTOGRAMMETRY','FUSION',
                                  'SIMULATION','ADVISORY','DONE','FAILED')),
  error_message TEXT,
  odm_task_id   TEXT,
  dem_path      TEXT,
  ortho_path    TEXT,
  mesh_path     TEXT,
  photo_dir     TEXT NOT NULL,
  photos        INTEGER,
  aligned       INTEGER,
  align_ratio   REAL,
  processing_s  INTEGER,
  gsd_cm        REAL,
  stage         TEXT,
  fusion_path   TEXT,
  advisory_path TEXT,
  heightmap_path TEXT
);

CREATE TABLE IF NOT EXISTS hotspot (
  id               TEXT PRIMARY KEY,
  mission_id       TEXT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
  lat              REAL NOT NULL,
  lon              REAL NOT NULL,
  elevation_m      REAL,
  slope_deg        REAL,
  aspect_deg       REAL,
  fire_confidence  REAL,
  smoke_confidence REAL,
  source           TEXT NOT NULL CHECK (source IN ('YOLO','LORA','MANUAL')),
  detected_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hotspot_mission ON hotspot(mission_id);

CREATE TABLE IF NOT EXISTS prediction (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  hotspot_id      TEXT NOT NULL REFERENCES hotspot(id) ON DELETE CASCADE,
  horizon_min     INTEGER NOT NULL,
  predicted_lat   REAL NOT NULL,
  predicted_lon   REAL NOT NULL,
  risk_level      TEXT NOT NULL CHECK (risk_level IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  slope_weight    REAL,
  wind_weight     REAL,
  rate_m_min      REAL,
  model_version   TEXT
);

CREATE TABLE IF NOT EXISTS weather_obs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  mission_id    TEXT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
  observed_at   TEXT NOT NULL,
  wind_speed_kmh   REAL,
  wind_dir_deg     REAL,
  humidity_pct     REAL,
  temperature_c    REAL,
  source           TEXT DEFAULT 'open-meteo',
  is_cached        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS advisory (
  id               TEXT PRIMARY KEY,
  mission_id       TEXT NOT NULL REFERENCES mission(id) ON DELETE CASCADE,
  severity         TEXT NOT NULL CHECK (severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
  narrative        TEXT,
  action_ids_json  TEXT NOT NULL,
  model            TEXT NOT NULL,
  prompt_sha       TEXT NOT NULL,
  seed             INTEGER NOT NULL,
  dropped_ids      TEXT,
  error            TEXT,
  generated_at     TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    return db


def init_db(path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    db = connect(path)
    db.executescript(SCHEMA)
    db.commit()
    return db


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r else None


def upsert_mission(db: sqlite3.Connection, m: dict[str, Any]) -> None:
    started = m.get("started_at") or now()
    db.execute(
        """
        INSERT INTO mission (id, mission_mode, started_at, photo_dir, status, stage,
                             area_m2, odm_task_id, dem_path, ortho_path, mesh_path,
                             photos, aligned, align_ratio, processing_s, gsd_cm,
                             fusion_path, advisory_path, heightmap_path)
        VALUES (:id, :mission_mode, :started_at, :photo_dir, :status, :stage,
                :area_m2, :odm_task_id, :dem_path, :ortho_path, :mesh_path,
                :photos, :aligned, :align_ratio, :processing_s, :gsd_cm,
                :fusion_path, :advisory_path, :heightmap_path)
        ON CONFLICT(id) DO UPDATE SET
          status=excluded.status, stage=excluded.stage, area_m2=excluded.area_m2,
          odm_task_id=excluded.odm_task_id, dem_path=excluded.dem_path,
          ortho_path=excluded.ortho_path, mesh_path=excluded.mesh_path,
          photos=excluded.photos, aligned=excluded.aligned,
          align_ratio=excluded.align_ratio, processing_s=excluded.processing_s,
          gsd_cm=excluded.gsd_cm, fusion_path=excluded.fusion_path,
          advisory_path=excluded.advisory_path, heightmap_path=excluded.heightmap_path
        """,
        {
            "id": m["id"],
            "mission_mode": m.get("mission_mode", "PRE_FIRE"),
            "started_at": started,
            "photo_dir": m.get("photo_dir", ""),
            "status": m.get("status", "CAPTURING"),
            "stage": m.get("stage", m.get("status", "CAPTURING")),
            "area_m2": m.get("area_m2"),
            "odm_task_id": m.get("odm_task_id"),
            "dem_path": m.get("dem_path"),
            "ortho_path": m.get("ortho_path"),
            "mesh_path": m.get("mesh_path"),
            "photos": m.get("photos"),
            "aligned": m.get("aligned"),
            "align_ratio": m.get("align_ratio"),
            "processing_s": m.get("processing_s"),
            "gsd_cm": m.get("gsd_cm"),
            "fusion_path": m.get("fusion_path"),
            "advisory_path": m.get("advisory_path"),
            "heightmap_path": m.get("heightmap_path"),
        },
    )
    db.commit()


def update_mission(db: sqlite3.Connection, mission_id: str, **fields: Any) -> None:
    allowed = {
        "status", "stage", "area_m2", "odm_task_id", "dem_path", "ortho_path",
        "mesh_path", "photo_dir", "photos", "aligned", "align_ratio",
        "processing_s", "gsd_cm", "fusion_path", "advisory_path",
        "heightmap_path", "error_message", "ended_at",
    }
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    sets = ", ".join(f"{k}=?" for k in clean)
    db.execute(f"UPDATE mission SET {sets} WHERE id=?", [*clean.values(), mission_id])
    db.commit()


def replace_hotspots(db: sqlite3.Connection, mission_id: str, spots: Iterable[dict]) -> None:
    db.execute("DELETE FROM hotspot WHERE mission_id=?", (mission_id,))
    for s in spots:
        db.execute(
            """INSERT INTO hotspot (id, mission_id, lat, lon, elevation_m, slope_deg,
               aspect_deg, fire_confidence, smoke_confidence, source, detected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                s["id"], mission_id, s["lat"], s["lon"], s.get("elevation_m"),
                s.get("slope_deg"), s.get("aspect_deg"), s.get("fire_confidence"),
                s.get("smoke_confidence"), s.get("source", "MANUAL"),
                s.get("detected_at") or now(),
            ),
        )
    db.commit()


def replace_predictions(db: sqlite3.Connection, mission_id: str, preds: Iterable[dict]) -> None:
    db.execute(
        "DELETE FROM prediction WHERE hotspot_id IN (SELECT id FROM hotspot WHERE mission_id=?)",
        (mission_id,),
    )
    for p in preds:
        db.execute(
            """INSERT INTO prediction (hotspot_id, horizon_min, predicted_lat,
               predicted_lon, risk_level, slope_weight, wind_weight, rate_m_min,
               model_version) VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                p["hotspot_id"], p["horizon_min"], p["predicted_lat"],
                p["predicted_lon"], p["risk_level"], p.get("slope_weight"),
                p.get("wind_weight"), p.get("rate_m_min"),
                p.get("model_version", "pyroscan-0.1"),
            ),
        )
    db.commit()


def add_weather(db: sqlite3.Connection, mission_id: str, w: dict) -> None:
    db.execute(
        """INSERT INTO weather_obs (mission_id, observed_at, wind_speed_kmh,
           wind_dir_deg, humidity_pct, temperature_c, source, is_cached)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            mission_id, w.get("observed_at") or now(), w.get("wind_speed_kmh"),
            w.get("wind_dir_deg"), w.get("humidity_pct"), w.get("temperature_c"),
            w.get("source", "open-meteo"), 1 if w.get("is_cached") else 0,
        ),
    )
    db.commit()


def upsert_advisory(db: sqlite3.Connection, mission_id: str, a: dict) -> None:
    db.execute(
        """INSERT OR REPLACE INTO advisory (id, mission_id, severity, narrative,
           action_ids_json, model, prompt_sha, seed, dropped_ids, error, generated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            a.get("id", f"ADV-{mission_id}"), mission_id, a["severity"],
            a.get("summary_narrative") or a.get("narrative") or "",
            __import__("json").dumps(a.get("action_ids", [])),
            a.get("model", "template"), a.get("prompt_sha", ""),
            int(a.get("seed", 0)), __import__("json").dumps(a.get("dropped_ids", [])),
            a.get("error"), a.get("generated_at") or now(),
        ),
    )
    db.commit()


def get_mission(db: sqlite3.Connection, mission_id: str) -> dict | None:
    return _row(db.execute("SELECT * FROM mission WHERE id=?", (mission_id,)).fetchone())


def latest_mission(db: sqlite3.Connection) -> dict | None:
    return _row(db.execute("SELECT * FROM mission ORDER BY started_at DESC LIMIT 1").fetchone())


def list_missions(db: sqlite3.Connection, limit: int = 50) -> list[dict]:
    return [dict(r) for r in db.execute(
        "SELECT * FROM mission ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()]


def mission_bundle(db: sqlite3.Connection, mission_id: str) -> dict | None:
    m = get_mission(db, mission_id)
    if not m:
        return None
    spots = [dict(r) for r in db.execute(
        "SELECT * FROM hotspot WHERE mission_id=? ORDER BY id", (mission_id,)
    ).fetchall()]
    preds = [dict(r) for r in db.execute(
        """SELECT p.* FROM prediction p JOIN hotspot h ON h.id=p.hotspot_id
           WHERE h.mission_id=? ORDER BY p.horizon_min""", (mission_id,)
    ).fetchall()]
    weather = _row(db.execute(
        "SELECT * FROM weather_obs WHERE mission_id=? ORDER BY id DESC LIMIT 1", (mission_id,)
    ).fetchone())
    adv = _row(db.execute(
        "SELECT * FROM advisory WHERE mission_id=? ORDER BY generated_at DESC LIMIT 1", (mission_id,)
    ).fetchone())
    return {"mission": m, "hotspots": spots, "predictions": preds,
            "weather": weather, "advisory": adv}
