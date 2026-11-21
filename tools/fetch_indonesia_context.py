"""Fetch the wider 2D-map base: Indonesia plus surrounding seas and neighbours.

NASA GIBS Blue Marble shaded relief + bathymetry over 88-150E, 20S-10N,
4096x2000 (~1.6 km/px). Public domain, bundled so the map is real texture
everywhere the viewport can reach.
"""
from pathlib import Path

import requests
from PIL import Image
import io

OUT = Path(__file__).resolve().parent.parent / "spike" / "web" / "data" / "skin_satellite.jpg"
URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
BBOX = "88,-20,150,10"
SIZE = (4096, 2000)
PARAMS = {
    "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetMap",
    "LAYERS": "BlueMarble_ShadedRelief_Bathymetry", "SRS": "EPSG:4326",
    "BBOX": BBOX, "WIDTH": SIZE[0], "HEIGHT": SIZE[1],
    "FORMAT": "image/jpeg",
}


def main() -> None:
    resp = requests.get(URL, params=PARAMS, timeout=300)
    resp.raise_for_status()
    if not resp.headers.get("Content-Type", "").startswith("image/"):
        raise SystemExit(f"not an image: {resp.text[:160]}")
    image = Image.open(io.BytesIO(resp.content))
    if image.size != SIZE:
        raise SystemExit(f"unexpected size: {image.size}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(OUT, quality=86, optimize=True)
    print(f"wrote {OUT} {SIZE[0]}x{SIZE[1]} {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
