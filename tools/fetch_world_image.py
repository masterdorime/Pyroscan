"""Fetch the bundled world base image for the Indonesia globe (build-time only).

NASA GIBS Blue Marble shaded relief + bathymetry, public domain, 5400x2700.
NASA's eoimages host is not reachable on every network; GIBS is.
"""
from pathlib import Path

import requests
from PIL import Image
import io

OUT = Path(__file__).resolve().parent.parent / "spike" / "web" / "data" / "world_blue_marble.jpg"
URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
PARAMS = {
    "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
    "LAYERS": "BlueMarble_ShadedRelief_Bathymetry", "SRS": "EPSG:4326",
    "BBOX": "-180,-90,180,90", "WIDTH": 5400, "HEIGHT": 2700,
    "FORMAT": "image/jpeg",
}


def main() -> None:
    r = requests.get(URL, params=PARAMS, timeout=300)
    r.raise_for_status()
    if not r.headers.get("Content-Type", "").startswith("image/"):
        raise SystemExit(f"not an image: {r.text[:160]}")
    image = Image.open(io.BytesIO(r.content))
    if image.size != (5400, 2700):
        raise SystemExit(f"unexpected size: {image.size}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(OUT, quality=88)
    print(f"wrote {OUT}  {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
