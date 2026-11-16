"""Convert an ODM task directory into dashboard assets."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image, ImageEnhance

Image.MAX_IMAGE_PIXELS = None


def _find(task: Path, *candidates: str) -> Path:
    for c in candidates:
        p = task / c
        if p.exists():
            return p
    raise FileNotFoundError(f"none of {candidates} under {task}")


def _stats(task: Path) -> dict:
    path = task / "odm_report" / "stats.json"
    if not path.exists():
        return {}
    stats = json.loads(path.read_text(encoding="utf-8"))
    rec = stats.get("reconstruction_statistics", {})
    proc = stats.get("odm_processing_statistics", {})
    proc_all = stats.get("processing_statistics", {})
    images_dir = task / "images"
    submitted = len([p for p in images_dir.glob("*") if p.is_file()]) if images_dir.exists() else None
    aligned = rec.get("reconstructed_shots_count")
    ratio = round(aligned / submitted, 3) if submitted and aligned else None
    return {
        "images_submitted": submitted,
        "images_aligned": aligned,
        "align_ratio": ratio,
        "rmse_reprojection_px": rec.get("reprojection_error_pixels"),
        "processing_s": round(proc.get("total_time", 0)),
        "processing_human": proc.get("total_time_human"),
        "gsd_cm": round(float(proc.get("average_gsd", 0)), 2) or None,
        "area_m2": round(float(proc_all["area"]), 1) if proc_all.get("area") else None,
    }


def _bounds(task: Path) -> dict:
    info = task / "odm_georeferencing" / "odm_georeferenced_model.info.json"
    bbox = json.loads(info.read_text(encoding="utf-8"))["stats"]["bbox"]["EPSG:4326"]["bbox"]
    return {"west": bbox["minx"], "south": bbox["miny"],
            "east": bbox["maxx"], "north": bbox["maxy"]}


def export_odm_assets(task_dir: Path | str, out_dir: Path | str,
                      size: int = 384, tex: int = 4096) -> dict:
    task = Path(task_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    dsm_path = _find(task, "odm_dem/dsm.tif", "odm_dem/dsm.original.tif", "odm_dem.tif")
    ortho_path = _find(task, "odm_orthophoto/odm_orthophoto.tif")
    bounds = _bounds(task)
    stats = _stats(task)

    a = tifffile.imread(dsm_path).astype(np.float32)
    valid = np.isfinite(a) & (a > -1000)
    if not valid.any():
        raise ValueError("DSM has no valid pixels")
    fill = float(np.median(a[valid]))
    a = np.where(valid, a, fill)
    h = np.array(Image.fromarray(a, mode="F").resize((size, size), Image.BILINEAR), dtype=np.float32)

    payload = {
        "mission_id": task.name,
        "width": size, "height": size,
        "west": bounds["west"], "south": bounds["south"],
        "east": bounds["east"], "north": bounds["north"],
        "height_scale_m": 1.0,
        "geoid_offset_m": 0.0,
        "base_height_m": 0.0,
        "h_min": round(float(h.min()), 2),
        "h_max": round(float(h.max()), 2),
        "heights_m": [round(float(v), 2) for v in h.ravel()],
    }
    hm_path = out / "heightmap.json"
    hm_path.write_text(json.dumps(payload), encoding="utf-8")

    ortho = Image.open(ortho_path).convert("RGBA")
    r, g, b, alpha = ortho.split()
    rgb = Image.merge("RGB", (r, g, b))
    rgb = ImageEnhance.Contrast(rgb).enhance(1.15)
    rgb = ImageEnhance.Color(rgb).enhance(1.25)
    rgb = ImageEnhance.Sharpness(rgb).enhance(1.15)
    ortho = Image.merge("RGBA", (*rgb.split(), alpha))
    ortho.thumbnail((tex, tex), Image.LANCZOS)
    ortho_path_out = out / "ortho.webp"
    ortho.save(ortho_path_out, "WEBP", quality=85, method=6)

    # Hillshade the ortho so relief reads without overlays.
    lat_c = (bounds["south"] + bounds["north"]) / 2.0
    width_m = (bounds["east"] - bounds["west"]) * 111320.0 * math.cos(math.radians(lat_c))
    height_m = (bounds["north"] - bounds["south"]) * 111320.0
    dx = width_m / max(size - 1, 1)
    dy = height_m / max(size - 1, 1)
    gy, gx = np.gradient(h, dy, dx)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    hs = np.sin(math.radians(42)) * np.cos(slope) + \
        np.cos(math.radians(42)) * np.sin(slope) * np.cos(math.radians(315) - aspect)
    hs = np.clip(hs, 0, 1)
    hs_img = Image.fromarray(hs.astype(np.float32), "F").resize(ortho.size, Image.BICUBIC)
    hs_a = np.array(hs_img)
    rgb_a = np.array(ortho.convert("RGB"), dtype=np.float32)
    shaded = np.dstack([
        np.clip(rgb_a * (0.58 + 0.42 * hs_a)[..., None], 0, 255).astype(np.uint8),
        np.array(ortho.getchannel("A")),
    ])
    shaded_path = out / "ortho_shaded.webp"
    Image.fromarray(shaded, "RGBA").save(shaded_path, "WEBP", quality=88, method=6)

    meta = {"stats": stats, "bounds": bounds,
            "h_min": payload["h_min"], "h_max": payload["h_max"]}
    (out / "assets.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {
        "heightmap_path": str(hm_path),
        "ortho_path": str(ortho_path_out),
        "ortho_shaded_path": str(shaded_path),
        "meta": meta,
        **stats,
    }


