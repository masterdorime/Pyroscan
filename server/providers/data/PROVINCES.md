# Province boundaries — source, licence, regeneration

`provinces.geojson` is the bundled admin-1 catalogue used by the Indonesia and
Province levels. The app never fetches boundaries at runtime.

## Source and licence

- **Geometry:** OpenStreetMap `admin_level=4` relations, extracted with
  Overpass. Data © OpenStreetMap contributors, licensed **ODbL 1.0**
  (https://www.openstreetmap.org/copyright). The database in this file is
  distributed under ODbL 1.0.
- **Land clipping:** Natural Earth 10 m land, **public domain**
  (https://www.naturalearthdata.com/about/terms-of-use/).

OSM's administrative relations include maritime boundaries. Central Kalimantan,
for example, is 229,481 km² before clipping and ~154,500 km² after. Every
province is clipped to land at build time, so sea does not become part of the
province shape.

## Schema

```json
{"type": "Feature", "properties": {
  "name": "Kalimantan Tengah", "iso": "ID-KT",
  "bbox": [110.68, -3.54, 115.85, 0.79], "area_km2": 154475
}, "geometry": {"type": "MultiPolygon"}}
```

38 features, including the 2022 splits: Papua Selatan, Papua Tengah,
Papua Pegunungan, Papua Barat Daya. `iso` is the unique key.

## Regeneration

```powershell
pip install shapely
python tools/build_provinces.py
```

Build-time only. Overpass is live, so regeneration drifts as OSM is edited;
commit the generated file and re-run deliberately. Natural Earth land is cached
under `tools/.cache/` (gitignored).
