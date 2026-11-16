"""Brighton Beach DSM -> Cesium heightmap + demo ortho. Stdlib + numpy/PIL/tifffile."""
import json
import math
import os
import statistics

import numpy as np
import tifffile
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DSM = os.path.join(ROOT, "data", "brighton_beach", "dsm.tif")
IMAGES = os.path.join(ROOT, "data", "brighton_beach", "images")
OUT = os.path.join(ROOT, "web", "data")
SIZE = 256


def dms(v, ref):
    d = v[0] + v[1] / 60 + v[2] / 3600
    return -d if ref in ("S", "W") else d


def mean_gps():
    pts = []
    for name in os.listdir(IMAGES):
        g = Image.open(os.path.join(IMAGES, name)).getexif().get_ifd(34853)
        if g and 2 in g and 4 in g:
            pts.append((dms(g[2], g[1]), dms(g[4], g[3])))
    return statistics.mean(p[0] for p in pts), statistics.mean(p[1] for p in pts)


def main():
    os.makedirs(OUT, exist_ok=True)
    raw = tifffile.imread(DSM).astype(np.float32)
    rows_full, cols_full = raw.shape
    valid = raw > -1000

    # Crop the nodata border so the DSM fills the tile instead of sitting on a plateau.
    rs = np.where(valid.any(axis=1))[0]
    cs = np.where(valid.any(axis=0))[0]
    r0, r1 = int(rs[0]), int(rs[-1]) + 1
    c0, c1 = int(cs[0]), int(cs[-1]) + 1
    raw = raw[r0:r1, c0:c1]
    valid = valid[r0:r1, c0:c1]

    filled = np.where(valid, raw, np.float32(np.median(raw[valid])))
    h = np.array(
        Image.fromarray(filled, mode="F").resize((SIZE, SIZE), Image.BILINEAR),
        dtype=np.float32,
    )

    lat, lon = mean_gps()
    scale = 0.07015431312445902  # from ModelPixelScaleTag
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(lat))
    west_full = lon - (cols_full * scale) / (2 * m_per_deg_lon)
    north_full = lat + (rows_full * scale) / (2 * m_per_deg_lat)
    west = west_full + (c0 * scale) / m_per_deg_lon
    east = west_full + (c1 * scale) / m_per_deg_lon
    north = north_full - (r0 * scale) / m_per_deg_lat
    south = north_full - (r1 * scale) / m_per_deg_lat

    # Cesium draws a skirt down to the ellipsoid, so absolute 160 m heights become
    # a pedestal. Render relative to a local datum and feather the edges to zero.
    base = float(h.min())
    rel = h - base

    def feather(n, frac=0.12):
        w = np.ones(n, dtype=np.float32)
        k = max(1, int(n * frac))
        ramp = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, k))).astype(np.float32)
        w[:k] = ramp
        w[-k:] = ramp[::-1]
        return w

    alpha = np.outer(feather(SIZE), feather(SIZE))
    rel = rel * alpha

    payload = {
        "mission_id": "SPIKE_BRIGHTON_001",
        "width": SIZE,
        "height": SIZE,
        "west": west,
        "south": south,
        "east": east,
        "north": north,
        "height_scale_m": 1.0,
        "geoid_offset_m": 0.0,
        "base_height_m": round(base, 2),
        "h_min": round(float(rel.min()), 2),
        "h_max": round(float(rel.max()), 2),
        "heights_m": [round(float(v), 2) for v in rel.ravel()],
    }
    with open(os.path.join(OUT, "heightmap.json"), "w") as f:
        json.dump(payload, f)

    # Hillshade + ramp + a fake burn scar, purely to test imagery over terrain.
    gy, gx = np.gradient(h)
    shade = np.clip(0.55 - gx * 1.8 + gy * 1.8, 0.15, 1.0)
    norm = (h - h.min()) / max(h.max() - h.min(), 1e-6)
    rgb = np.stack(
        [90 + 70 * norm, 95 + 60 * norm, 60 + 35 * norm], axis=-1
    ) * shade[..., None]
    ortho = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).resize(
        (1024, 1024), Image.BICUBIC
    ).convert("RGBA")
    edge = Image.fromarray((alpha * 255).astype(np.uint8)).resize(
        (1024, 1024), Image.BICUBIC
    )
    ortho.putalpha(edge)
    d = ImageDraw.Draw(ortho)
    d.polygon(
        [(560, 300), (760, 340), (820, 520), (700, 650), (520, 560), (480, 400)],
        fill=(45, 42, 40, 255),
    )
    ortho.save(os.path.join(OUT, "ortho.png"))

    meta = {
        "bounds": [west, south, east, north],
        "h_min": float(h.min()),
        "h_max": float(h.max()),
        "valid_pixels": int(valid.sum()),
        "source_pixels": int(raw.size),
    }
    with open(os.path.join(OUT, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
