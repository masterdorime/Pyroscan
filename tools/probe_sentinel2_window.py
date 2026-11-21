"""Standalone probe: does the Sentinel-2 scene actually cover our window?

Run:
    python tools/probe_sentinel2_window.py                # live STAC + remote COG
    python tools/probe_sentinel2_window.py --offline      # cached envelope only
    python tools/probe_sentinel2_window.py --href <url>   # one known scene
    python tools/probe_sentinel2_window.py --href <path.tif> --extent W,S,E,N

It prints every quantity the adapter depends on and then shows what
`read_scene_window` computes for the same inputs. It never writes production
state: no cache, no DB, no dashboard.

Nothing here is imported by the app.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _print(label: str, value) -> None:
    print(f"{label:<42} {value}")


def _fmt_bounds(b) -> str:
    return f"W{b[0]:.6f} S{b[1]:.6f} E{b[2]:.6f} N{b[3]:.6f}"


def _densified_boundary(extent, n: int = 64):
    """Boundary of the 4326 window as n points per edge, closed."""
    w, s, e, n_ = extent.west, extent.south, extent.east, extent.north
    pts = []
    for i in range(n):
        t = i / n
        pts.append((w + (e - w) * t, s))
    for i in range(n):
        t = i / n
        pts.append((e, s + (n_ - s) * t))
    for i in range(n):
        t = i / n
        pts.append((e - (e - w) * t, n_))
    for i in range(n):
        t = i / n
        pts.append((w, n_ - (n_ - s) * t))
    return pts


def probe_geometry(source: str, extent, *, size: int = 1024) -> dict:
    """Independent, verbose computation of the window. Returns a report dict."""
    import numpy as np
    import rasterio
    from rasterio.warp import transform, transform_bounds
    from rasterio.windows import from_bounds

    report: dict = {"source": source, "size": size}
    env = {"GDAL_HTTP_TIMEOUT": "30", "GDAL_HTTP_CONNECTTIMEOUT": "10",
           "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"}

    with rasterio.Env(**env):
        with rasterio.open(source) as ds:
            report["driver"] = ds.driver
            report["crs"] = str(ds.crs)
            report["crs_units"] = ds.crs.linear_units if ds.crs else None
            report["width"] = ds.width
            report["height"] = ds.height
            report["count"] = ds.count
            report["dtypes"] = list(ds.dtypes)
            report["bounds"] = tuple(ds.bounds)
            report["transform"] = tuple(ds.transform)[:6]
            report["res"] = tuple(ds.res)
            report["tiled"] = bool(ds.profile.get("tiled"))

            # --- mission window in 4326 --------------------------------
            report["window_4326"] = (extent.west, extent.south,
                                     extent.east, extent.north)
            report["centre_4326"] = extent.centre

            # --- transform to raster CRS -------------------------------
            # transform_bounds densifies the edges. Record the default and the
            # result of a much denser pass so an edge effect would show up.
            tb = transform_bounds("EPSG:4326", ds.crs,
                                  extent.west, extent.south,
                                  extent.east, extent.north)
            tb_dense = transform_bounds("EPSG:4326", ds.crs,
                                        extent.west, extent.south,
                                        extent.east, extent.north,
                                        densify_pts=256)
            report["window_raster"] = tuple(tb)
            report["window_raster_dense"] = tuple(tb_dense)
            report["densify_delta"] = tuple(abs(a - b) for a, b in zip(tb, tb_dense))

            xs, ys = transform("EPSG:4326", ds.crs, [extent.centre[1]],
                               [extent.centre[0]])
            report["centre_raster"] = (xs[0], ys[0])

            # --- coverage checks ---------------------------------------
            b = ds.bounds
            cx, cy = xs[0], ys[0]
            report["centre_inside_bounds"] = bool(
                b.left <= cx <= b.right and b.bottom <= cy <= b.top)
            report["centre_inside_pixel_grid"] = bool(
                -0.5 <= ds.index(cx, cy)[0] <= ds.height - 0.5
                and -0.5 <= ds.index(cx, cy)[1] <= ds.width - 0.5)

            pts = _densified_boundary(extent, n=64)
            lons = [p[0] for p in pts]
            lats = [p[1] for p in pts]
            bx, by = transform("EPSG:4326", ds.crs, lons, lats)
            outside = [(x, y) for x, y in zip(bx, by)
                       if not (b.left <= x <= b.right and b.bottom <= y <= b.top)]
            report["ring_points"] = len(pts)
            report["ring_points_outside"] = len(outside)
            report["ring_fully_covered"] = not outside
            report["ring_epsilon"] = min(
                (min(x - b.left, b.right - x, y - b.bottom, b.top - y)
                 for x, y in zip(bx, by)), default=None)

            # --- clipping, as the adapter does it ----------------------
            left = max(tb[0], b.left)
            bottom = max(tb[1], b.bottom)
            right = min(tb[2], b.right)
            top = min(tb[3], b.top)
            report["clipped_raster"] = (left, bottom, right, top)
            report["clip_loss"] = (tb[0] - left, tb[1] - bottom,
                                   right - tb[2], top - tb[3])
            report["clipped_nonempty"] = bool(left < right and bottom < top)

            if report["clipped_nonempty"]:
                raw = from_bounds(left, bottom, right, top, transform=ds.transform)
                report["window_raw"] = (raw.col_off, raw.row_off,
                                        raw.width, raw.height)
                win = raw.round_offsets().round_lengths()
                report["window_rounded"] = (win.col_off, win.row_off,
                                            win.width, win.height)
                report["window_pixels"] = (int(win.width), int(win.height))
                report["window_valid"] = bool(win.width >= 1 and win.height >= 1)
                # expected pixel size from the CRS transform
                report["expected_px"] = (
                    (right - left) / ds.res[0], (top - bottom) / ds.res[1])

                # --- actual read ---------------------------------------
                picked = [1, 2, 3] if ds.count >= 3 else [1]
                try:
                    array = ds.read(picked, window=win)
                    report["read_shape"] = tuple(array.shape)
                    report["read_min"] = int(np.min(array)) if array.size else None
                    report["read_max"] = int(np.max(array)) if array.size else None
                    report["read_mean"] = float(np.mean(array)) if array.size else None
                    report["read_unique"] = int(np.unique(array).size) if array.size else 0
                    report["read_ok"] = True
                except Exception as exc:  # noqa: BLE001 - the probe reports it
                    report["read_ok"] = False
                    report["read_error"] = f"{type(exc).__name__}: {exc}"
            else:
                report["window_valid"] = False
    return report


def print_report(rep: dict) -> None:
    print("=" * 78)
    _print("source", rep["source"])
    _print("driver", rep.get("driver"))
    _print("raster CRS", rep.get("crs"))
    _print("raster size (cols x rows)", f'{rep.get("width")} x {rep.get("height")}')
    _print("band count / dtype", f'{rep.get("count")} {rep.get("dtypes")}')
    _print("raster bounds", _fmt_bounds(rep["bounds"]) if rep.get("bounds") else None)
    _print("raster res", rep.get("res"))
    _print("raster transform", rep.get("transform"))
    _print("tiled", rep.get("tiled"))
    print("-" * 78)
    _print("mission centre (lat, lon)", rep.get("centre_4326"))
    _print("window 4326", _fmt_bounds(rep["window_4326"]))
    _print("centre in raster CRS", rep.get("centre_raster"))
    _print("window in raster CRS", _fmt_bounds(rep["window_raster"])
           if rep.get("window_raster") else None)
    _print("  densify_pts=256", _fmt_bounds(rep["window_raster_dense"])
           if rep.get("window_raster_dense") else None)
    _print("  densify delta", rep.get("densify_delta"))
    print("-" * 78)
    _print("centre inside raster bounds", rep.get("centre_inside_bounds"))
    _print("centre inside pixel grid", rep.get("centre_inside_pixel_grid"))
    _print("ring boundary points", rep.get("ring_points"))
    _print("  outside raster", rep.get("ring_points_outside"))
    _print("ring fully covered", rep.get("ring_fully_covered"))
    _print("  min distance to edge (m)", rep.get("ring_epsilon"))
    print("-" * 78)
    _print("clipped window in raster CRS", _fmt_bounds(rep["clipped_raster"])
           if rep.get("clipped_raster") else None)
    _print("clip loss (l,b,r,t)", rep.get("clip_loss"))
    _print("clipped window non-empty", rep.get("clipped_nonempty"))
    _print("window raw (col, row, w, h)", rep.get("window_raw"))
    _print("window rounded (col, row, w, h)", rep.get("window_rounded"))
    _print("window pixel size", rep.get("window_pixels"))
    _print("expected pixel size", rep.get("expected_px"))
    _print("window valid", rep.get("window_valid"))
    _print("read ok", rep.get("read_ok"))
    _print("read shape", rep.get("read_shape"))
    _print("read min/max/mean", (rep.get("read_min"), rep.get("read_max"),
                                 rep.get("read_mean")))
    _print("read unique values", rep.get("read_unique"))
    if rep.get("read_error"):
        _print("read error", rep["read_error"])


def compare_with_adapter(href: str, extent, *, size: int = 256) -> None:
    """Show what the production function does for the same inputs."""
    from server.providers.sentinel2 import read_scene_window

    print("-" * 78)
    try:
        pixels = read_scene_window(href, extent, size=size)
        print(f"read_scene_window -> OK shape={pixels.shape} "
              f"mean={pixels.mean():.1f} min={pixels.min()} max={pixels.max()}")
    except Exception as exc:  # noqa: BLE001 - the probe reports it
        print(f"read_scene_window -> {type(exc).__name__}: {exc}")


def cached_extent(mission_id: str):
    """Rebuild the exact extent the last fetch used, from the mission heightmap.

    Do not rebuild it from `context_dem.envelope.json`: that bbox is the *clipped*
    ring, so its centre is not the mission centre (it was 7.5 km off here).
    """
    from server.providers.geo import mission_extent
    from server.providers.sentinel2 import imagery_extent

    hm = json.loads((ROOT / "spike" / "missions" / mission_id / "heightmap.json")
                    .read_text(encoding="utf-8"))
    return imagery_extent(mission_extent(hm, 15.0))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--href", help="scene COG URL or local .tif path")
    ap.add_argument("--mission", default="SPIKE_BRIGHTON_ODM")
    ap.add_argument("--extent", help="W,S,E,N override in EPSG:4326")
    ap.add_argument("--offline", action="store_true",
                    help="do not call STAC; use the fixture search response")
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    from server.providers.base import Extent

    if args.extent:
        w, s, e, n = (float(v) for v in args.extent.split(","))
        extent = Extent(west=w, south=s, east=e, north=n, ring_km=15.0)
    else:
        extent = cached_extent(args.mission)

    print(f"extent 4326: {_fmt_bounds((extent.west, extent.south, extent.east, extent.north))}")
    print(f"centre: lat={extent.centre[0]:.6f} lon={extent.centre[1]:.6f}")

    hrefs: list[str] = []
    if args.href:
        hrefs = [args.href]
    else:
        from server.providers.sentinel2 import pick_scenes, search_scenes
        if args.offline:
            raw = json.loads((ROOT / "server/providers/fixtures/sentinel2/search.json")
                             .read_text(encoding="utf-8"))
            features = raw["features"]
        else:
            features = search_scenes(extent)
        print(f"STAC features: {len(features)}")
        shaped = pick_scenes(features)
        print(f"usable candidates: {len(shaped)}")
        for c in shaped[:5]:
            print(f"  {c['scene_id']:<32} cloud={c['cloud_pct']:.5f} "
                  f"{c['href'].split('/')[-4] if '/' in c['href'] else ''}")
        hrefs = [c["href"] for c in shaped[:3]]

    reports = []
    for href in hrefs:
        if args.offline and href.startswith(("http://", "https://")):
            print(f"skip (offline): {href}\n  pass --href <local.tif> to probe a raster")
            continue
        try:
            rep = probe_geometry(href, extent, size=args.size)
        except Exception as exc:  # noqa: BLE001
            print(f"\nOPEN FAILED for {href}\n  {type(exc).__name__}: {exc}")
            continue
        rep["scene_id"] = href.rstrip("/").split("/")[-2] if "/" in href else str(href)
        reports.append(rep)
        print_report(rep)
        if not args.json:
            compare_with_adapter(href, extent, size=32)

    if args.json:
        print(json.dumps(reports, indent=2, default=str))
    # Offline listing is a valid result even when no raster was read.
    return 0 if (reports or args.offline) else 1


if __name__ == "__main__":
    raise SystemExit(main())
