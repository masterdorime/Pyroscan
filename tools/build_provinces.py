"""Build the bundled 38-province boundary file (build-time only, not runtime).

Source: OpenStreetMap admin_level=4 relations (ODbL), clipped to Natural Earth
10 m land (public domain) so maritime boundaries do not become the province
shape. Output is committed; the app never fetches boundaries at runtime.

    python tools/build_provinces.py

Requires: requests, shapely. Network on first run (Overpass + Natural Earth).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import requests
import shapely
from shapely.geometry import LineString, mapping
from shapely.ops import linemerge, polygonize

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "server" / "providers" / "data" / "provinces.geojson"
CACHE = ROOT / "tools" / ".cache"
NE_LAND = CACHE / "ne_10m_land.geojson"
OVERPASS = "https://overpass-api.de/api/interpreter"
HEADERS = {"User-Agent": "PyroScan-build/0.1 (province boundaries)"}
SIMPLIFY = 0.002
INDONESIA_BBOX = (94.0, -12.0, 142.0, 8.0)

QUERY_IDS = (
    "[out:json][timeout:120];"
    'area["ISO3166-1"="ID"][admin_level=2]->.a;'
    'rel(area.a)["boundary"="administrative"]["admin_level"="4"];'
    "out ids tags;"
)
QUERY_GEOM = (
    "[out:json][timeout:600];"
    'area["ISO3166-1"="ID"][admin_level=2]->.a;'
    'rel(area.a)["boundary"="administrative"]["admin_level"="4"];'
    "out geom;"
)


def overpass(query: str, *, retries: int = 3) -> dict:
    for attempt in range(retries):
        r = requests.post(OVERPASS, data={"data": query}, headers=HEADERS,
                          timeout=900)
        if r.status_code == 200:
            return r.json()
        print("overpass", r.status_code, r.text[:120].replace("\n", " "))
        time.sleep(5 * (attempt + 1))
    raise SystemExit("Overpass failed")


def land_union():
    CACHE.mkdir(parents=True, exist_ok=True)
    if not NE_LAND.exists():
        url = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
               "master/geojson/ne_10m_land.geojson")
        print("downloading Natural Earth land")
        r = requests.get(url, timeout=600)
        r.raise_for_status()
        NE_LAND.write_bytes(r.content)
    data = json.loads(NE_LAND.read_text(encoding="utf-8"))
    polys = []
    w, s, e, n = INDONESIA_BBOX
    for f in data["features"]:
        geom = shapely.geometry.shape(f["geometry"])
        gw, gs, ge, gn = geom.bounds
        if ge < w or gw > e or gn < s or gs > n:
            continue
        polys.append(geom)
    print("land polygons near Indonesia", len(polys))
    return shapely.union_all(polys)


def area_km2(geom) -> int:
    total = 0.0
    parts = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    for poly in parts:
        ring = list(poly.exterior.coords)
        if len(ring) < 4:
            continue
        lat0 = sum(y for _, y in ring) / len(ring)
        kx = 111.32 * math.cos(math.radians(lat0))
        a = 0.0
        for i in range(len(ring) - 1):
            x1, y1 = ring[i]
            x2, y2 = ring[i + 1]
            a += (x1 * kx) * (y2 * 111.32) - (x2 * kx) * (y1 * 111.32)
        total += abs(a) / 2
    return int(total)


def assemble(members: list[dict]) -> shapely.Geometry | None:
    outer, inner = [], []
    for m in members:
        geom = m.get("geometry")
        if m.get("type") != "way" or not geom or len(geom) < 2:
            continue
        line = LineString([(p["lon"], p["lat"]) for p in geom])
        (inner if m.get("role") == "inner" else outer).append(line)
    if not outer:
        return None

    def rings(lines):
        union = shapely.union_all(lines)
        merged = union if union.geom_type == "LineString" else linemerge(union)
        parts = [merged] if merged.geom_type == "LineString" else list(merged.geoms)
        return [p for p in polygonize(parts) if p.area > 1e-9]

    out = rings(outer)
    if not out:
        return None
    shape = shapely.union_all(out)
    holes = rings(inner)
    if holes:
        shape = shape.difference(shapely.union_all(holes))
    return shape if not shape.is_empty else None


def main():
    print("querying relation ids")
    meta = {e["id"]: e.get("tags", {}) for e in overpass(QUERY_IDS)["elements"]}
    print("relations", len(meta))
    data = overpass(QUERY_GEOM)
    rels = {e["id"]: e for e in data["elements"] if e["type"] == "relation"}
    print("with geometry", len(rels))

    land = land_union()
    features = []
    for rid, tags in meta.items():
        name = tags.get("name")
        iso = tags.get("ISO3166-2")
        if not name or not iso:
            print("skip (no name/iso)", rid, tags)
            continue
        rel = rels.get(rid)
        if not rel:
            print("skip (no geometry)", name)
            continue
        geom = assemble(rel.get("members", []))
        if geom is None:
            print("skip (not assembled)", name)
            continue
        geom = geom.intersection(land)
        if geom.is_empty:
            print("skip (no land)", name)
            continue
        geom = geom.simplify(SIMPLIFY, preserve_topology=True)
        if geom.geom_type not in ("Polygon", "MultiPolygon"):
            print("skip (type)", name, geom.geom_type)
            continue
        w, s, e, n = geom.bounds
        features.append({
            "type": "Feature",
            "properties": {
                "name": name,
                "iso": iso,
                "bbox": [round(w, 4), round(s, 4), round(e, 4), round(n, 4)],
                "area_km2": area_km2(geom),
            },
            "geometry": mapping(geom),
        })
        print(f"  {iso:<6} {name:<28} {features[-1]['properties']['area_km2']:>8} km2")

    features.sort(key=lambda f: f["properties"]["iso"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                              separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT}  {len(features)} provinces  {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
