"""Polling folder watcher. One operator, one laptop: stdlib is enough."""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from . import config, db
from .pipeline.runner import run_mission


def scan_once() -> list[str]:
    config.ensure_dirs()
    conn = db.init_db()
    done = []
    for folder in sorted(config.INBOX.iterdir()):
        if not folder.is_dir():
            continue
        images = [p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
        if not images:
            continue
        row = conn.execute("SELECT id FROM mission WHERE photo_dir=?", (str(folder),)).fetchone()
        if row:
            continue
        mission_id = f"FLIGHT_{datetime.now():%Y%m%d_%H%M%S}"
        run_mission(folder, mission_id=mission_id, mode="PRE_FIRE")
        done.append(mission_id)
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=5)
    args = ap.parse_args()
    print(f"watching {config.INBOX} every {args.interval}s")
    while True:
        try:
            for mid in scan_once():
                print("done", mid)
        except Exception as exc:
            print("error", exc)
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
