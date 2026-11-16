"""ODM task -> Cesium heightmap.json + ortho.webp."""
import json
import os
import sys

import numpy as np
import tifffile
from PIL import Image, ImageEnhance

Image.MAX_IMAGE_PIXELS = None

TASK = sys.argv[1] if len(sys.argv) > 1 else r"spike/data/c16574ae-dfd7-4ea2-a341-8c942fabf484"
OUT = r"spike/web/data"
SIZE = 256
TEX = 4096

info = json.load(open(os.path.join(TASK, "odm_georeferencing", "odm_georeferenced_model.info.json")))
bb = info["stats"]["bbox"]["EPSG:4326"]["bbox"]

a = tifffile.imread(os.path.join(TASK, "odm_dem", "dsm.tif")).astype(np.float32)
valid = np.isfinite(a) & (a > -1000)
fill = float(np.median(a[valid]))
a = np.where(valid, a, fill)
h = np.array(Image.fromarray(a, mode="F").resize((SIZE, SIZE), Image.BILINEAR), dtype=np.float32)

payload = {
    "mission_id": "SPIKE_BRIGHTON_ODM",
    "width": SIZE,
    "height": SIZE,
    "west": bb["minx"],
    "south": bb["miny"],
    "east": bb["maxx"],
    "north": bb["maxy"],
    "height_scale_m": 1.0,
    "geoid_offset_m": 0.0,
    "base_height_m": 0.0,
    "h_min": round(float(h.min()), 2),
    "h_max": round(float(h.max()), 2),
    "heights_m": [round(float(v), 2) for v in h.ravel()],
}
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "heightmap.json"), "w") as f:
    json.dump(payload, f)

ortho = Image.open(os.path.join(TASK, "odm_orthophoto", "odm_orthophoto.tif")).convert("RGBA")
r, g, b, a = ortho.split()
rgb = Image.merge("RGB", (r, g, b))
rgb = ImageEnhance.Contrast(rgb).enhance(1.15)
rgb = ImageEnhance.Color(rgb).enhance(1.25)
rgb = ImageEnhance.Sharpness(rgb).enhance(1.15)
ortho = Image.merge("RGBA", (*rgb.split(), a))
ortho.thumbnail((TEX, TEX), Image.LANCZOS)
ortho.save(os.path.join(OUT, "ortho.webp"), "WEBP", quality=85, method=6)

print(json.dumps({k: payload[k] for k in ("west", "south", "east", "north", "h_min", "h_max", "width", "height")}, indent=2))
print("ortho", ortho.size, os.path.getsize(os.path.join(OUT, "ortho.webp")) // 1024, "KB")
