"""Rebuild the dashboard base textures from the real DSM.

Outputs (spike/web/data):
  elevation.png       hillshade + hypsometric tint + 10 m contours (50 m index)
  severity_base.png   5-class burn severity, hillshaded
  heat.png            5-band detection density + isolines
  ortho_shaded.webp   orthophoto multiplied by hillshade
"""
import json
import math

import numpy as np
from PIL import Image, ImageFilter

HM = r"spike/web/data/heightmap.json"
ORTHO = r"spike/web/data/ortho.webp"
OUT = r"spike/web/data"
BASE = 2048
TEX = 4096


def boxblur(a, n=2):
    for _ in range(n):
        p = np.pad(a, 1, mode="edge")
        a = (
            p[:-2, :-2] + p[:-2, 1:-1] + p[:-2, 2:]
            + p[1:-1, :-2] + p[1:-1, 1:-1] + p[1:-1, 2:]
            + p[2:, :-2] + p[2:, 1:-1] + p[2:, 2:]
        ) / 9.0
    return a


def dilate(m):
    return m | np.roll(m, 1, 0) | np.roll(m, -1, 0) | np.roll(m, 1, 1) | np.roll(m, -1, 1)


def hillshade(z, dx, dy, az=315.0, alt=42.0):
    gy, gx = np.gradient(z, dy, dx)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    hs = np.sin(math.radians(alt)) * np.cos(slope) + \
        np.cos(math.radians(alt)) * np.sin(slope) * np.cos(math.radians(az) - aspect)
    return np.clip(hs, 0, 1)


def ramp(t, stops):
    t = np.clip(t, 0, 1)
    out = np.zeros(t.shape + (3,), dtype=np.float32)
    for i in range(len(stops) - 1):
        a, ca = stops[i]
        b, cb = stops[i + 1]
        m = (t >= a) & (t <= b)
        f = np.where(m, (t - a) / max(b - a, 1e-6), 0)
        for c in range(3):
            out[..., c] = np.where(m, ca[c] + (cb[c] - ca[c]) * f, out[..., c])
    return out


def main():
    meta = json.loads(open(HM, encoding="utf-8").read())
    w, h = int(meta["width"]), int(meta["height"])
    lat = (meta["south"] + meta["north"]) / 2
    width_m = (meta["east"] - meta["west"]) * 111320.0 * math.cos(math.radians(lat))
    height_m = (meta["north"] - meta["south"]) * 111320.0
    dx, dy = width_m / (w - 1), height_m / (h - 1)

    z0 = np.array(meta["heights_m"], dtype=np.float32).reshape(h, w)
    z = boxblur(z0, 2)
    zmin, zmax = float(z.min()), float(z.max())
    hs = hillshade(z, dx, dy)

    # Footprint mask from the orthophoto alpha.
    ortho = Image.open(ORTHO).convert("RGBA")
    mask = np.array(ortho.getchannel("A").resize((BASE, BASE), Image.BILINEAR), dtype=np.float32) / 255.0
    mask[mask < 0.12] = 0
    mask = boxblur(mask, 1)

    zB = np.array(Image.fromarray(z, mode="F").resize((BASE, BASE), Image.BICUBIC))
    hsB = np.array(Image.fromarray(hs.astype(np.float32), mode="F").resize((BASE, BASE), Image.BICUBIC))
    zr = (zB - zmin) / max(zmax - zmin, 1e-6)

    # --- elevation base -----------------------------------------------------
    tint = ramp(zr, [
        (0.0, (58, 90, 70)),
        (0.45, (128, 132, 86)),
        (0.75, (190, 172, 116)),
        (1.0, (226, 212, 172)),
    ])
    shade = 0.58 + 0.42 * hsB
    rgb = np.clip(tint * shade[..., None], 0, 255)

    zone2 = np.floor((zB - zmin) / 2.0)
    edge2 = np.zeros_like(zone2, dtype=bool)
    edge2[1:, :] |= zone2[1:, :] != zone2[:-1, :]
    edge2[:, 1:] |= zone2[:, 1:] != zone2[:, :-1]
    zone10idx = np.floor((zB - zmin) / 10.0)
    edge10idx = np.zeros_like(zone10idx, dtype=bool)
    edge10idx[1:, :] |= zone10idx[1:, :] != zone10idx[:-1, :]
    edge10idx[:, 1:] |= zone10idx[:, 1:] != zone10idx[:, :-1]
    edge10idx = dilate(edge10idx)

    rgba = np.zeros((BASE, BASE, 4), dtype=np.uint8)
    rgba[..., :3] = rgb.astype(np.uint8)
    rgba[..., 3] = (255 * mask).astype(np.uint8)
    rgba[edge2] = [24, 24, 24, 175]
    rgba[edge10idx] = [229, 169, 84, 240]
    rgba[..., 3] = (rgba[..., 3] * mask).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(rf"{OUT}\elevation.png")

    # --- terrain hybrid: shaded photo + tint + contours ----------------------
    ob = Image.open(rf"{OUT}\ortho_shaded.webp").convert("RGBA").resize((BASE, BASE), Image.LANCZOS)
    rgb_ob = np.array(ob.convert("RGB"), dtype=np.float32)
    tint_norm = tint / 255.0
    hyb = np.clip(rgb_ob * (0.72 + 0.28 * tint_norm), 0, 255).astype(np.uint8)
    hyb_rgba = np.zeros((BASE, BASE, 4), dtype=np.uint8)
    hyb_rgba[..., :3] = hyb
    hyb_rgba[..., 3] = np.array(ob.getchannel("A"))
    hyb_rgba[edge2] = [24, 24, 24, 130]
    hyb_rgba[edge10idx] = [229, 169, 84, 220]
    hyb_rgba[..., 3] = (hyb_rgba[..., 3] * mask).astype(np.uint8)
    Image.fromarray(hyb_rgba, "RGBA").save(rf"{OUT}\terrain_base.webp", "WEBP", quality=88, method=6)

    # --- severity base ------------------------------------------------------
    yy, xx = np.mgrid[0:BASE, 0:BASE]
    xu, yv = xx / BASE, 1.0 - yy / BASE
    dxu, dyv = xu - 0.5, yv - 0.5
    r = np.sqrt((dxu / 1.08) ** 2 + dyv**2)
    a = np.arctan2(dyv, dxu)
    r = r * (1.0 + 0.12 * np.sin(3 * a) + 0.05 * np.sin(7 * a + 1.3))
    sev = np.zeros((BASE, BASE, 4), dtype=np.uint8)
    classes = [
        (0.10, (92, 43, 40), 235),
        (0.17, (194, 69, 47), 220),
        (0.24, (224, 138, 60), 205),
        (0.31, (229, 193, 90), 190),
        (0.40, (111, 191, 143), 170),
    ]
    prev = 0.0
    for hi, color, alpha in classes:
        m = (r >= prev) & (r < hi)
        sev[m] = [*color, alpha]
        prev = hi
    shadeS = 0.60 + 0.40 * hsB
    sev[..., :3] = np.clip(sev[..., :3] * shadeS[..., None], 0, 255).astype(np.uint8)
    sev[..., 3] = (sev[..., 3] * mask).astype(np.uint8)
    Image.fromarray(sev, "RGBA").save(rf"{OUT}\severity_base.png")

    # --- heat overlay -------------------------------------------------------
    ang = math.radians(45)
    field = np.zeros((BASE, BASE), dtype=np.float32)
    for u, v, s in [(0.46, 0.54, 0.045), (0.55, 0.47, 0.038), (0.61, 0.40, 0.030)]:
        dxu, dyv = xu - u, yv - v
        xr = dxu * math.cos(ang) + dyv * math.sin(ang)
        yr = -dxu * math.sin(ang) + dyv * math.cos(ang)
        field += np.exp(-(xr**2 / (2 * (s * 1.9) ** 2) + yr**2 / (2 * s**2)))
    field = np.clip((field / field.max() - 0.06) / 0.94, 0, 1)
    bins = np.digitize(field, [0.2, 0.4, 0.6, 0.8])
    colors = [
        (255, 220, 120, 15),
        (255, 180, 80, 70),
        (255, 120, 50, 120),
        (229, 68, 59, 165),
        (255, 240, 210, 220),
    ]
    heat = np.zeros((BASE, BASE, 4), dtype=np.uint8)
    for i, color in enumerate(colors):
        heat[bins == i] = color
    edge = np.zeros((BASE, BASE), dtype=bool)
    edge[1:, :] |= bins[1:, :] != bins[:-1, :]
    edge[:, 1:] |= bins[:, 1:] != bins[:, :-1]
    edge = dilate(edge)
    heat[edge] = [255, 245, 220, 190]
    heat[..., 3] = (heat[..., 3] * mask).astype(np.uint8)
    Image.fromarray(heat, "RGBA").save(rf"{OUT}\heat.png")

    # --- shaded orthophoto --------------------------------------------------
    hs_tex = np.array(Image.fromarray(hs.astype(np.float32), mode="F").resize(ortho.size, Image.BICUBIC))
    rgb_o = np.array(ortho.convert("RGB"), dtype=np.float32)
    shade_o = (0.58 + 0.42 * hs_tex)[..., None]
    out = np.dstack([np.clip(rgb_o * shade_o, 0, 255).astype(np.uint8),
                     np.array(ortho.getchannel("A"))])
    Image.fromarray(out, "RGBA").save(rf"{OUT}\ortho_shaded.webp", "WEBP", quality=88, method=6)

    # --- contact shadow -------------------------------------------------------
    S = 512
    yy, xx = np.mgrid[0:S, 0:S]
    dx = (xx - S / 2) / (S / 2)
    dy = (yy - S / 2) / (S / 2)
    r = np.sqrt(dx * dx + dy * dy)
    alpha = np.clip((1 - r) ** 2, 0, 1) * 150
    shadow = np.zeros((S, S, 4), dtype=np.uint8)
    shadow[..., 3] = alpha.astype(np.uint8)
    Image.fromarray(shadow, "RGBA").filter(ImageFilter.GaussianBlur(26)).save(
        rf"{OUT}\shadow.png"
    )

    # --- studio floor: dark radial gradient + faint grid --------------------
    S = 1024
    yy, xx = np.mgrid[0:S, 0:S]
    r = np.sqrt((xx - S / 2) ** 2 + (yy - S / 2) ** 2) / (S / 2)
    floor = np.zeros((S, S, 3), dtype=np.float32)
    center_c = np.array([18, 22, 25], dtype=np.float32)
    edge_c = np.array([7, 8, 10], dtype=np.float32)
    for i in range(3):
        floor[..., i] = edge_c[i] + (center_c[i] - edge_c[i]) * np.clip(1 - r, 0, 1) ** 1.5
    grid = (xx % 128 == 0) | (yy % 128 == 0)
    floor[grid] = np.clip(floor[grid] + np.array([26, 34, 40]), 0, 255)
    floor_alpha = (255 * np.clip(1 - r, 0, 1) ** 1.5).astype(np.uint8)
    Image.fromarray(np.dstack([floor.astype(np.uint8), floor_alpha]), "RGBA").save(
        rf"{OUT}\studio_floor.png"
    )

    # --- near context crop for the minimap ---------------------------------
    fx = json.loads(open(rf"{OUT}\fixtures.json", encoding="utf-8").read())
    cb = fx["context"]
    padx = (meta["east"] - meta["west"]) * 1.2
    pady = (meta["north"] - meta["south"]) * 1.2
    nb = {
        "west": meta["west"] - padx, "east": meta["east"] + padx,
        "south": meta["south"] - pady, "north": meta["north"] + pady,
    }
    orig = Image.open(rf"{OUT}\context.jpg").convert("RGB")
    x0 = int((nb["west"] - cb["west"]) / (cb["east"] - cb["west"]) * orig.width)
    x1 = int((nb["east"] - cb["west"]) / (cb["east"] - cb["west"]) * orig.width)
    y0 = int((cb["north"] - nb["north"]) / (cb["north"] - cb["south"]) * orig.height)
    y1 = int((cb["north"] - nb["south"]) / (cb["north"] - cb["south"]) * orig.height)
    orig.crop((max(0, x0), max(0, y0), min(orig.width, x1), min(orig.height, y1))).save(
        rf"{OUT}\context_near.jpg", quality=90
    )

    # --- bright landscape texture: graded context + soft edge alpha ---------
    ctx = Image.open(rf"{OUT}\context.jpg").convert("RGB")
    arr = np.asarray(ctx).astype(np.float32) / 255.0
    arr = np.power(arr, 0.86)                       # lift the shadows
    arr = np.clip((arr - 0.5) * 1.08 + 0.5, 0, 1)   # gentle contrast
    gray = arr @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    arr = np.clip(gray[..., None] + (arr - gray[..., None]) * 1.18, 0, 1)
    arr[..., 0] *= 1.07
    arr[..., 1] *= 1.02
    arr[..., 2] *= 0.94
    arr = np.clip(arr * 1.12, 0, 1)
    h, w = arr.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    dx = (xx - w / 2) / (w / 2)
    dy = (yy - h / 2) / (h / 2)
    r = np.sqrt(dx * dx + dy * dy)
    alpha = np.clip((1.0 - r) / 0.16, 0, 1)
    rgba = np.dstack([(arr * 255).astype(np.uint8), (alpha * 255).astype(np.uint8)])
    Image.fromarray(rgba, "RGBA").filter(
        ImageFilter.UnsharpMask(radius=2, percent=110, threshold=3)
    ).save(rf"{OUT}\context_bright.png")

    # --- paper base variants: feathered footprint edge ----------------------
    paper = [
        ("terrain_base.webp", "terrain_base_paper.webp", "WEBP"),
        ("elevation.png", "elevation_paper.png", "PNG"),
        ("severity_base.png", "severity_base_paper.png", "PNG"),
        ("ortho_shaded.webp", "ortho_shaded_paper.webp", "WEBP"),
    ]
    for src, dst, fmt in paper:
        im = Image.open(rf"{OUT}\{src}").convert("RGBA")
        blur = max(24, int(im.width * 0.06))
        im.putalpha(im.getchannel("A").filter(ImageFilter.GaussianBlur(blur)))
        if fmt == "WEBP":
            im.save(rf"{OUT}\{dst}", "WEBP", quality=88, method=6)
        else:
            im.save(rf"{OUT}\{dst}")

    print("elevation, severity_base, heat, ortho_shaded, terrain_base, shadow, studio_floor, context_near, context_bright, paper variants written",
          "z", round(zmin, 1), round(zmax, 1))


if __name__ == "__main__":
    main()



