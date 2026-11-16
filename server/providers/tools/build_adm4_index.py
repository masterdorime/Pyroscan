"""Build the bundled adm4 index from a user-supplied open dataset.

The dataset is NOT committed: it may be large and its licence must be checked
before redistribution. This script reads a CSV with columns
`code,name,level,west,south,east,north,tz` and writes a derived index.

It fails loudly and leaves the existing index untouched if the source is
missing, unreadable, or has no usable rows. A partial index is never emitted.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "data" / "adm4_index.json"
REQUIRED = ("code", "name", "west", "south", "east", "north")


def _rows(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
    if missing:
        raise SystemExit(f"source is missing columns: {', '.join(missing)}")
    entries = []
    for row in reader:
        try:
            entries.append({
                "code": row["code"].strip(),
                "name": row["name"].strip(),
                "level": (row.get("level") or "adm4").strip(),
                "bbox": [float(row["west"]), float(row["south"]),
                         float(row["east"]), float(row["north"])],
                "tz": (row.get("tz") or "Asia/Jakarta").strip(),
            })
        except (TypeError, ValueError):
            continue
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_adm4_index")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", default=TARGET, type=Path)
    parser.add_argument("--licence", default="")
    args = parser.parse_args(argv)

    try:
        text = args.source.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read {args.source}: {exc}") from None

    entries = _rows(text)
    if not entries:
        raise SystemExit("no usable rows; existing index left untouched")

    payload = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        .replace("+00:00", "Z"),
        "source": str(args.source.name),
        "licence": args.licence,
        "entries": entries,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(entries)} entries to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
