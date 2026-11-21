"""Fetch the bundled Indonesia crop for the globe's regional LOD (build-time only).

NASA GIBS Blue Marble shaded relief + bathymetry over the archipelago,
4096x1700 (~1.2 km/px). Same WMS 1.1.1 request shape as
`tools/fetch_world_image.py`; 1.3.0 needs a TIME value, 1.1.1 does not.
Public domain, committed so the app stays offline.
"""
from pathlib import Path

import requests
from PIL import Image
import io

OUT = Path(__file__).resolve().parent.parent / "spike" / "web" / "data" / "indonesia_blue_marble.jpg"
URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
BBOX = "94,-12,142,8"          # lon,lat order for WMS 1.1.1 (EPSG:4326)
SIZE = (4096, 1700)
PARAMS = {
    "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
    "LAYERS": "BlueMarble_ShadedRelief_Bathymetry", "SRS": "EPSG:4326",
    "BBOX": BBOX, "WIDTH": SIZE[0], "HEIGHT": SIZE[1],
    "FORMAT": "image/jpeg",
}


def main() -> None:
    r = requests.get(URL, params=PARAMS, timeout=300)
    r.raise_for_status()
    if not r.headers.get("Content-Type", "").startswith("image/"):
        raise SystemExit(f"not an image: {r.text[:160]}")
    image = Image.open(io.BytesIO(r.content))
    if image.size != SIZE:
        raise SystemExit(f"unexpected size: {image.size}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(OUT, quality=86)
    kb = OUT.stat().st_size // 1024
    if OUT.stat().st_size >= 5 * 1024 * 1024:
        raise SystemExit(f"too large for a bundled asset: {kb} KB")
    print(f"wrote {OUT}  {SIZE[0]}x{SIZE[1]}  {kb} KB")


if __name__ == "__main__":
    main()
