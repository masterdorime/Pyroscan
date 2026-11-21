# PyroScan — Indonesia First: Globe, Provinces, and Recon

**Date:** 2026-11-19
**Status:** Slices 1–4 implemented (2026-11-19/20). The Indonesia renderer was
then replaced by a Canvas 2D map with four skins (2026-11-20); the Cesium globe
code remains only as dormant history and for the mission modes. Country FIRMS
counts and dots, masked province preview plates, an explicit 59 m detail tile,
province and dot panels with Drone disabled, and a `Recon here` stub all work
on the 2D map. Limits: plates are mosaics of dates with ~60 % coverage and
cloud; recon is still mission-scoped. Per-province labels on the map are not
built.
**Builds on:** `2026-11-18-wide-terrain-and-regional.md`,
`2026-11-17-mission-modes-and-spread-visualization.md`
**Evidence:** `spike/shots/province-plate-mock.png`,
`spike/shots/province-plate-mock-click.png`,
`spike/shots/mock/plate.html` (throwaway)

---

## 1. The problem

The dashboard is still a one-site demo. There is no way to choose an area, and
FIRMS exists only as a text card. The product claim is Indonesia-first; the
interface starts at Brighton.

The mock proved the interaction is right and exposed the data limits:

- A province-wide **single-date** mosaic covered **49 %** of Central Kalimantan.
- A **composite** of 28 per-tile least-cloudy scenes (22 Aug – 14 Oct 2026)
  covered **62 %**; cloud survives where every date was cloudy.
- FIRMS rejects `days=7` (`Invalid day range. Expects [1..5]`); VIIRS returned
  **0 rows**, MODIS returned **86–120** for the same 5 days, 7–10 inside the
  province.
- Placing rotated UTM tiles into lat/lon rectangles tears at province scale;
  the mock fixed it with `WarpedVRT`. The production 60 km reader has the same
  latent distortion.

So the design must treat province imagery as a **labelled composite with
holes**, not an atlas plate.

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Entry level | **Indonesia** mode, globe, 1–2 km bundled base | visual entry, no tile server |
| Base source | **bundled NASA Blue Marble / Natural Earth** | public domain, offline-safe |
| Camera | clamped to Indonesia + margin | the globe must not promise global data |
| Coverage rule | `COVERAGE · INDONESIA`; Brighton is a labelled demo | honest scope |
| Province unit | **OSM admin_level=4, 38 provinces**, land-clipped | the only free set with the 2022 splits |
| FIRMS at country scale | **one Indonesia query**, points → provinces | 38 calls is wasteful |
| Province imagery | **composite preview** (250–400 m), holes show the base | single-date is unusable |
| Selected province | **59 m detail**, lazy | fidelity when zoomed, not at plate scale |
| Province gaps | base map underneath, never a flat fill | holes must not read as data |
| Detail handoff | click a dot → 60 km recon (existing) | the working scale stays sharp |
| Drone | survey-gated only | a FIRMS pixel is not a flight |

## 3. Levels

| Level | Extent | Imagery | Terrain | Data |
|---|---|---|---|---|
| **Indonesia** | archipelago | 1–2 km bundled | none | province borders + counts |
| **Province** | province bbox | ~250–350 m composite | none | clipped imagery + dots |
| **Recon** | 60 km | 59 m mosaic | 4-tile DEM | existing Regional |
| **Terrain** | 4 km | 10 m | 2-tile DEM | existing Terrain |
| **Drone** | 143 m | 1.6 cm | DSM | ODM survey only |

The globe is shown only at Indonesia and Province. `scene.globe.show` is
switched off for Recon/Terrain/Drone so the existing paper look does not regress.

## 4. Data

### 4.1 Boundaries

**Chosen source:** OpenStreetMap `admin_level=4` relations, extracted with
Overpass, **38 provinces including the four 2022 Papua splits**, clipped to
Natural Earth 10 m land. Licence: **ODbL 1.0** for the polygons
(© OpenStreetMap contributors) plus **public domain** Natural Earth for the
clip. The generated `provinces.geojson` is committed; the app stays offline and
has no runtime geometry dependency.

Why not the obvious sources (all checked 2026-11-19):

| Source | Units | Why not |
|---|---|---|
| OCHA COD via HDX (`cod-ab-idn`) | 34 | ADM1 still 2020; 456 MB archive |
| GADM 4.1 | 34 | no splits; non-commercial licence |
| geoBoundaries `gbOpen` | 34 | 2017 |
| geoBoundaries `gbHumanitarian` | 34 | 2019 |
| **OSM / Overpass** | **38** | chosen |

Build notes, measured on Central Kalimantan:

- OSM relation 2388613: 51 members, 779 KB of Overpass JSON;
  tags `name=Kalimantan Tengah`, `ISO3166-2=ID-KT` (`ref=KT-22` is unreliable).
- The relation includes **maritime area**: 229,481 km² versus ~153,500 km² of
  land. Clipping to Natural Earth 10 m land yields ~154,000 km² — correct.
- After clipping and 0.002° simplification (~220 m): **24 KB per province**,
  ~1 MB for all 38. Multi-part provinces stay MultiPolygons.
- Build step (`tools/build_provinces.py`, dev-only, shapely + network) writes
  `server/providers/data/provinces.geojson` with `name`, `iso`, `bbox`,
  centroid. The file and its ODbL/attribution note are committed.

If OSM is ever unavailable at build time, the committed file is used; the app
never fetches boundaries at runtime.

### 4.2 Province imagery

Two tiers, one provider:

- `province_<code>_preview.webp` — **2048 px** over the province bbox
  (≈250–350 m; Central Kalimantan lands at ~280 m), a **multi-date
  darkest-pixel composite** of the least-cloudy scene per intersecting tile,
  up to 28 scenes.
- `province_<code>_detail.webp` — 59 m, on selection, same bbox.

Both are polygon-masked at encode time (alpha outside the boundary) and warped
with `WarpedVRT`; no axis-aligned placement. The envelope records `scenes`,
`date_range`, `coverage`, `tier`, `multi_date`, `attribution`.

Measured in the mock: 28 scenes, 2026-08-22 – 2026-10-14, coverage 0.62,
**475 m/px at 1200 px** — the mock was deliberately cheaper than the preview
tier. Preview target ≈ 2–4 MB each; detail ≈ 10–25 MB.

### 4.3 FIRMS

- One query over `95,-11,141,6`, `days=5` (API maximum), VIIRS then MODIS.
- Reuse the parser; aggregate per province with a bbox prefilter + point-in-polygon.
- Return `count`, `max_frp`, `newest_age_s`, and a capped dot list per province.
- Site views keep the existing 15/60 km query; the country query is separate.

## 5. API

- `GET /api/v1/provinces` → catalogue + per-province fire summary.
- `GET /api/v1/provinces/{code}/imagery?tier=preview|detail`.
- `GET /api/v1/overview/fires?days=5` → aggregated country fires (cached 2 h).
- `GET /api/v1/missions/latest` unchanged; `context` becomes per-mission later.
- Click → `POST /api/v1/recon` is **not** in this slice: recon reuses the site
  flow from the next slice. A dot click at province level opens the card and
  offers `Recon here`, which this slice stubs with its coordinates.

## 6. Client

- **Indonesia**: globe, bundled base, atmosphere, province borders, count labels,
  FIRMS clusters, `COVERAGE · INDONESIA`.
- **Province**: fly to bbox; attach preview layer via `SingleTileImageryProvider`
  (one at a time), dim the rest, warm border, dots, chips
  (`N scenes · date range · coverage · <resolution> m preview`).
- **Dot click**: selection ring, card (sensor, time, FRP, confidence, distance),
  `Recon here`, `Close`. `Esc` closes.
- **Detail**: when selected, request the detail tier; swap when ready; badge goes
  `250 m preview` → `59 m`.
- **Fallback**: no province imagery → base + borders + dots, chip says
  `imagery unavailable`; no base → plain dark globe with borders.

## 7. Honesty rules

- A composite is labelled `composite`, with its date range and coverage.
- Holes show the base map, never a flat colour that reads as land.
- Province badges state tier and resolution; 59 m never appears at plate scale.
- `COVERAGE · INDONESIA` is always visible; sites outside are refused with a
  reason, not silently empty.
- Drone is disabled with `no survey at this detection` for any FIRMS dot.

## 8. Performance

- Globe + one 1024–1600 px province texture + dots. No per-frame work.
- Country FIRMS aggregation is cached; point-in-polygon is bbox-prefiltered.
- Target p95 under 40 ms at 1600×900 on the current machine (globe is heavier
  than the flat scene; measure, do not assume).

## 9. Tests (offline)

- Boundaries: **38 features**, all `iso` set and unique, every geometry valid
  after the land clip, no feature smaller than its known land area by more than
  a few percent, Central Kalimantan within 145–165 k km².
- `provinces.py`: point-in-polygon against known points (inside/outside/edge),
  bbox prefilter correctness.
- Aggregation: dots assigned once, counts match a fixture, `max_frp` and newest
  age correct, cap respected.
- Province provider: synthetic UTM tiles + a polygon mask → alpha outside is 0,
  inside is 255; coverage recorded; warped placement keeps tile edges straight.
- Envelope/route: preview only when cached; detail requested only on selection.
- Client: texture registration, tier badge, fallback without imagery.
- Browser: Indonesia → Province → card → `Recon here` stub; offline shell.

## 10. Out of scope

- Province-level terrain (3D) — the DEM stays in Recon/Terrain.
- Per-province 59 m for all 38 at build time.
- Real recon fetch and site model — next slice.
- Place labels, roads, admin-2/4.
- World coverage or a global FIRMS view.

## 11. Risks

1. **Boundary source.** Resolved: OSM has 38, ODbL, land-clipped at build time.
   Remaining risk is the **ODbL share-alike on the boundary database** and
   regeneration drift (OSM is live). Mitigation: commit the generated file with
   its attribution and build note; regeneration is manual.
2. **Coverage.** 62 % in this season is the honest ceiling. The base-under-gaps
   rule is what keeps it from looking broken.
3. **Texture limits.** 59 m over a large province approaches Cesium's 16384 px
   cap (Papua ≈ 11.9k px). Clamp and record.
4. **Globe regression.** Enabling the globe changes depth, fog and camera; it must
   be off outside Indonesia/Province.
5. **First fetch.** 28 scene reads can take minutes on this link; prefetch and
   cache, and never block the plate on the detail tier.

## 12. Slices

1. **Globe shell** — base, camera clamp, borders, coverage label (no dots).
2. **Province counts** — FIRMS country query, aggregation, labels.
3. **Province plate** — preview provider, mask, card, fallback.
4. **Detail tier** — lazy 59 m, tier badge.

Each slice leaves the dashboard working offline.
