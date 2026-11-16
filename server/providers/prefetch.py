"""Prefetch a mission's provider keys before going offline.

    python -m server.providers.prefetch --mission <id> [--only weather]
    python -m server.providers.prefetch --offline      # refuse the network
"""
from __future__ import annotations

import argparse
import json
import sys

from .gateway import Gateway, default_gateway, reset_default_gateway
from .geo import mission_extent


def run_prefetch(gw: Gateway, mission_id: str, extent, *,
                 keys: list[str] | None = None) -> list[dict]:
    """Refresh the requested keys and report what each one resolved to."""
    events: list[dict] = []
    for key in (keys or list(gw.registry)):
        if key not in gw.registry:
            continue
        if gw.cfg.offline:
            result = gw.get(mission_id, key, extent, allow_fetch=False)
        else:
            result = gw.refresh_now(mission_id, key, extent)
        events.append({
            "key": key,
            "status": result.status,
            "reason": result.reason,
            "age_s": result.age_s,
        })
    return events


def _extent_for(mission_id: str):
    from .. import db
    from ..pipeline import fusion

    mission = db.get_mission(db.init_db(), mission_id)
    if not mission:
        raise SystemExit(f"unknown mission: {mission_id}")
    path = mission.get("heightmap_path")
    if not path:
        raise SystemExit(f"mission {mission_id} has no heightmap")
    return mission_extent(fusion.load_heightmap(path), 15.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="prefetch")
    parser.add_argument("--mission", action="append", default=[])
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.offline:
        reset_default_gateway()

    gw = default_gateway()
    if args.offline:
        from dataclasses import replace
        gw = Gateway(gw.registry, replace(gw.cfg, offline=True), root=gw.root)

    missions = args.mission
    if not missions:
        from .. import db
        latest = db.latest_mission(db.init_db())
        if not latest:
            raise SystemExit("no missions")
        missions = [latest["id"]]

    report: list[dict] = []
    for mission_id in missions:
        extent = _extent_for(mission_id)
        events = run_prefetch(gw, mission_id, extent, keys=args.only or None)
        report.append({"mission_id": mission_id, "events": events})

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for block in report:
            for event in block["events"]:
                age = "?" if event["age_s"] is None else f"{event['age_s']}s"
                print(f"{block['mission_id']}  {event['key']:<16} "
                      f"{event['status']:<12} age {age}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
