#!/usr/bin/env python3
"""Inject the three GLB payloads into the studio template as base64.

Why embed instead of referencing sibling files: opening the HTML via file://
blocks XHR for adjacent .glb files (CORS), so the models silently fail to load
on a double-click. Base64 keeps it a single portable document.

    python simulation/build.py
"""

from __future__ import annotations

import base64
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
SRC = ROOT / "src" / "studio.html"
OUT = ROOT / "pyroscan_payload_studio.html"

ASSETS = {
    "__B64_DRONE__": "drone_low_poly.glb",
    "__B64_PHONE__": "smartphone.glb",
    "__B64_ESP32__": "esp32.glb",
}


def main() -> int:
    if not SRC.exists():
        print(f"missing template: {SRC}", file=sys.stderr)
        return 1

    html = SRC.read_text(encoding="utf-8")

    for token, filename in ASSETS.items():
        path = ROOT / "assets" / filename
        if not path.exists():
            print(f"missing asset: {path}", file=sys.stderr)
            return 1
        if html.count(token) != 1:
            print(f"{token} appears {html.count(token)}x in template (want 1)", file=sys.stderr)
            return 1
        raw = path.read_bytes()
        html = html.replace(token, base64.b64encode(raw).decode("ascii"))
        print(f"  embedded {filename:<22} {len(raw) / 1024:7.1f} KB")

    leftover = [t for t in ASSETS if t in html]
    if leftover:
        print(f"unreplaced placeholders: {leftover}", file=sys.stderr)
        return 1

    OUT.write_text(html, encoding="utf-8")
    print(f"\n{OUT.name}: {OUT.stat().st_size / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
