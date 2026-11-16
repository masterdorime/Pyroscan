"""Import an existing ODM task into the PyroScan database."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import config
from .pipeline.runner import run_mission

DEFAULT_TASK = config.ROOT / "spike" / "data" / "c16574ae-dfd7-4ea2-a341-8c942fabf484"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=str(DEFAULT_TASK))
    ap.add_argument("--mission", default="SPIKE_BRIGHTON_ODM")
    ap.add_argument("--llm", action="store_true", help="use Ollama for the narrative")
    args = ap.parse_args()

    task = Path(args.task)
    fixtures = json.loads((config.WEB / "data" / "fixtures.json").read_text(encoding="utf-8"))
    bundle = run_mission(
        photo_dir=task / "images",
        mission_id=args.mission,
        mode="PRE_FIRE",
        odm_task_dir=task,
        hotspots=fixtures["hotspots"],
        use_llm=args.llm,
    )
    m = bundle["mission"]
    print(json.dumps({
        "mission": m["id"],
        "status": m["status"],
        "photos": m["photos"],
        "aligned": m["aligned"],
        "align_ratio": m["align_ratio"],
        "area_m2": m["area_m2"],
        "advisory": bundle["advisory"]["severity"] if bundle.get("advisory") else None,
        "hotspots": len(bundle["hotspots"]),
        "predictions": len(bundle["predictions"]),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
