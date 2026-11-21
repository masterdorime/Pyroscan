# PyroScan — Mission Modes and Fire-Spread Visualization

**Date:** 2026-11-17
**Status:** Proposed — awaiting review. No code written for this scope.
**Builds on:** `2026-11-16-free-provider-layer-design.md` (the provider layer, shipped)
**Related:** `Docs/dashboard_design.md`, `Docs/HANDOFF.md`

---

## 1. The problem this fixes

The provider layer works and the dashboard does not show it. Weather, terrain,
imagery and fire detections all land as **text in one 340 px card**, while the
scene is still driven by the same fixture layers it used before any real data
existed. Two consequences:

- The console looks identical to its pre-provider version.
- The one fire-specific source returns **zero detections at Brighton**, so the
  most dramatic data can never appear.

Meanwhile the product's actual claim — *drone photogrammetry plus public data
predicts where a fire will spread* — has nowhere to be seen, because the
prediction is three static outlines computed from fixture wind.

This spec makes the data the **substrate** of the scene and the prediction its
**hero**.

---

## 2. Decisions

| Decision | Choice | Why |
|---|---|---|
| Mode model | Three authoritative tabs: **Drone · Terrain · Regional** | Explicit beats discovered-by-clicking; scales past two modes |
| Naming | `Regional`, not `Globe` | A 15–25 km ring is not a globe; the name must not promise scale we lack |
| Mode authority | The tab decides; zoom no longer switches mode | With three modes, zoom-driven switching becomes a surprise |
| Default mode | `drone` when a patch exists, else `terrain` | Show the unique asset when it exists; do not fake it when absent |
| Recon without a patch | **Terrain** is a first-class mode, not an error state | The console is useful before the drone flies |
| Spread output | **Growing front with a trail**, driven by per-bearing model output | The shape of the growth *is* the model's answer; a static outline hides it |
| Model inputs | Real where available, labelled per input | Wind and slope are real; fuel and ignition are fixtures |
| Imagery | Sentinel-2 (10 m) in Terrain/Regional | Pairs with 30 m terrain; the Esri crop stays a labelled fallback |

---

## 3. Mode contracts

| | **Drone** | **Terrain** | **Regional** |
|---|---|---|---|
| Surface | ODM patch (DSM 1.6 cm) | Copernicus DEM 30 m | DEM 30 m + ring layers |
| Camera preset | 220 m, −30° | 600 m, −25° | 3000 m, −45° |
| Range clamp | 150–400 m | 400 m–5 km | 2–40 km |
| Imagery | ODM ortho | Sentinel-2 or mosaic | Sentinel-2 or mosaic |
| Overlays | heat, prediction, hotspots, flight path | footprint marker, prediction | FIRMS, wind field, adm4 |
| Badge | `1.6 cm · 42 min` | `30 m · 4 h` | `15 km ring · 4 min` |
| Available when | patch exists | DEM cached | DEM cached |

`Drone` is **disabled with a reason** (`no reconstruction yet`), never silently
absent: a missing tab looks like a bug, a disabled tab looks like a state.

### 3.1 Transitions

Each tab animates to its preset camera over ~600 ms rather than teleporting.
Switching tabs does not reset layer choices within that mode; it remembers them
for the session.

### 3.2 Deep links

`#/<mission_id>/<mode>` — e.g. `#/SPIKE_BRIGHTON_ODM/terrain`. Unknown mode or
mission falls back to the default mode. This makes screenshots and demos
reproducible.

### 3.3 Badges are mandatory

Every mode badge states **resolution and data age** for its primary surface.
Switching tabs must never quietly change fidelity. A mode whose surface is
missing shows `fetching…` or `unavailable`, not a badge implying data.

---

## 4. Resolution honesty

The ladder is centimetres → tens of metres → kilometres, and the UI must never
flatten it.

1. **Contour interval follows the surface.** 2 m / 10 m index on the patch;
   10 m / 50 m on 30 m terrain.
2. **Derived values carry their cell size.** Slope, aspect and line-of-sight from
   30 m are shown as `30 m` values, with a note that a 10 m bank is invisible.
3. **The prediction label names its resolution** — `30 m model` or `1.6 cm model`.
4. **Camera clamp prevents over-zoom.** At 30 m per pixel, a 150 m camera range
   would imply detail that does not exist.
5. **No silent substitution.** Terrain never stands in for a patch without a mode
   change the user made.

---

## 5. The model

### 5.1 What changes

`spread.predict()` currently takes one wind vector plus the hotspot's slope and
returns two horizons. The front cannot be asymmetric because the inputs are not
directional beyond a single slope sample.

**New contract:** per bearing (every 10°, 36 samples), over horizons 0/30/60:

```json
{
  "model": {"id": "pyroscan-spread", "version": "2", "mode": "deterministic"},
  "resolution_m": 30,
  "origin": {"lat": -6.9195, "lon": 107.605, "source": "fixture"},
  "bearings": [
    {"deg": 0, "samples": [
      {"min": 0,  "radius_m": 0,   "rate_m_min": 0},
      {"min": 30, "radius_m": 38,  "rate_m_min": 1.27},
      {"min": 60, "radius_m": 92,  "rate_m_min": 1.53}
    ]}
  ],
  "inputs": [
    {"id": "wind",      "label": "Wind",      "source": "bmkg",       "age_s": 240,  "reality": "real"},
    {"id": "terrain",   "label": "Terrain",   "source": "copernicus-dem", "age_s": 14400, "reality": "real"},
    {"id": "fuel",      "label": "Fuel",      "source": "fixture",    "age_s": null, "reality": "fixture"},
    {"id": "pressure",  "label": "Pressure",  "source": "firms",      "age_s": 180,  "reality": "real"}
  ]
}
```

- `rate_m_min` per bearing = f(wind projection on that bearing, upslope component,
  fuel factor). Deterministic, no randomness.
- Radii are monotonic non-decreasing per bearing.
- `reality` is one of `real | fixture` and drives the label; it is never inferred
  by the UI.

### 5.2 Inputs and their effect

| Input | Drives | Removing it changes |
|---|---|---|
| Wind | downwind elongation | front becomes concentric |
| Terrain | upslope bias, run-out | front ignores slope |
| Fuel | base rate | rate scales, shape preserved |
| Pressure (FIRMS) | second ignition hazard | a risk marker appears/disappears |

Toggling an input re-runs the model and re-animates from the origin. This is the
demonstration that the data matters.

### 5.3 Ignition is a fixture and says so

The drone records heat signatures; it does not confirm a fire. The origin is
labelled `fixture` and the surface reads
`MODEL · real wind · real terrain · fixture fuel · hypothetical ignition`.

---

## 6. Rendering the front

- **Body:** filled polygon whose vertices are the per-bearing radii at the
  current scrubber time, semi-transparent, warm ramp.
- **Leading edge:** bright stroke with a label `4.1 m/min → NE`, taken from the
  fastest bearing.
- **Trail:** 4–6 ghost perimeters at earlier times, decreasing alpha, so history
  is readable without interaction.
- **Growth:** at 60 fps the front interpolates between the discrete samples;
  the scrubber sets the current time and the trail follows.
- **Playback:** play/pause and a 0–60 min scrubber. At each step the wind shown
  in the input strip is the wind *used* at that step.

Performance: one polygon rebuild per frame over 36 vertices is negligible; the
trail is five more. Under `prefers-reduced-motion`, growth snaps between samples
and the trail remains.

---

## 7. The input strip

Below the scene, above the forecast strip. One chip per model input:

```
WIND      BMKG · 12 km/h from 145° · 4 min   [real]     ●
TERRAIN   DSM 1.6 cm + DEM 30 m              [real]     ●
FUEL      severity fixture                   [SIMULASI] ○
PRESSURE  FIRMS · 0 in 15 km                 [real]     ●
```

- Dot = active in the model; click to toggle.
- Each chip shows its own age; a mixed-age model is therefore visible.
- A `fixture` chip is muted and marked `SIMULASI`, consistent with Phase 1.

---

## 8. Per-source surfaces

**FIRMS (Regional).** Detections sized by FRP, coloured by age (blueprint:
`Docs/references/ref-modis-fire-map.png`). A bearing spoke from the mission to
the nearest detection with distance in km. A 72 h dot timeline. **Zero
detections renders as coverage**, not emptiness: the ring is drawn with
`25,000 ha monitored · no detections in 24 h`. This is the single most important
fix for Brighton, where the honest answer is "nothing is burning nearby".

**BMKG (Terrain/Regional).** Wind rose at the mission; 3-hourly forecast strip
over 72 h; the resolves `adm4` boundary drawn as a polygon so the forecast's
administrative area is visible; a derived fire-weather gauge from wind ×
humidity × temperature. When `adm4` is unresolved, the strip says so and
Open-Meteo supplies the wind, with the reason visible.

**Copernicus DEM (Terrain).** Slope and aspect as toggleable surfaces; aspect
arrows across the ring; line-of-sight from the hotspot; a scale-truth strip
placing 30 m context beside the 1.6 cm patch.

**Sentinel-2 (Terrain/Regional).** Two dates, swipeable, latest against 90 days
earlier, with a change index. Scene date and cloud on the timeline chip.

---

## 9. States

| State | Behaviour |
|---|---|
| No patch, no DEM | Terrain and Drone both disabled with reasons; the shell still loads |
| Patch, no DEM | Drone available; Terrain disabled with `no context terrain` |
| DEM, no patch | **Recon**: Terrain available, Drone disabled `no reconstruction yet` |
| DEM fetching | Terrain shows the mosaic flat; badge `fetching…`; no error banner |
| Fires empty | Coverage statement (§8), never an error |
| Offline | Cached everything; badges carry age; `OFFLINE — cached data` |
| Model inputs stale | Chip shows age; label becomes `MODEL · stale wind (41 min)` |

---

## 10. Phases

1. **Mode shell.** Tabs, presets, clamps, badges, deep links, disabled reasons.
   Retire the Context pill and zoom-switching. No new data.
2. **Recon surface.** Generalise the context terrain mesh from the mosaic bbox to
   the ring; make it the Terrain surface; scale-aware contours and elevation
   profile from the DEM.
3. **Model.** Per-bearing spread from real wind and terrain; payload contract
   (§5.1); input chips with `reality`; a fixture ignition.
4. **Front rendering.** Growing front, trail, edge label, scrubber binding,
   reduced-motion path.
5. **Per-source surfaces.** FIRMS dots + coverage ring + 72 h timeline; BMKG rose
   + forecast strip + adm4 polygon; DEM slope/aspect/LOS; S2 swipe.
   **Includes fixing the Sentinel-2 read**: a neighbouring tile is currently
   selected for the 4 km window, so the read refuses and the view falls back.
   Phase 5 is blocked until a scene covering the window centre is guaranteed —
   the adapter already tries three candidates, so the remaining work is choosing
   the tile from the centre's UTM cell rather than from a STAC polygon that a
   neighbour can clip.
   **Resolved 2026-11-18:** ordering now prefers scenes whose bbox contains the
   window centre (see `Docs/HANDOFF.md` §9.19). What remains for this phase is
   the two-date swipe, not the read.

Each phase leaves the console working offline.

---

## 10a. Risks

1. **Sentinel-2 geometry (resolved 2026-11-18).** The imagery render was
   unresolved: `ring lies outside the imagery tile` for the correct tile, and a
   rasterio IO error for the one that previously worked. The cause was scene
   ranking, not the CRS maths; see `Docs/HANDOFF.md` §9.19. The 3-day cache TTL
   and the slow S3 path still mean a stale scene can be what renders.
2. **A 30 m prediction looks authoritative.** Coarse terrain produces confident
   looking fronts. Mitigation: the resolution is in the model label, the badge and
   the camera clamp.
3. **Fixture ignition in a real-data console.** The most visible object on screen
   starts from a fixture. Mitigation: `origin.source` in the payload, the words
   "hypothetical ignition" on the surface, and a fixture chip in the strip.
4. **Three modes multiply state.** Layer choices, camera and scrubber per mode.
   Mitigation: one mode object per session, no cross-mode layer leakage, and
   deep links for reproducibility.
5. **Per-bearing model credibility.** The coefficients are hand-set, not fitted to
   observed fire behaviour. It is a deterministic what-if, and must be described
   as one.

---

## 11. Tests

Offline, in the existing `server/providers/selftest.py` style plus browser checks.

- `spread` per bearing: radii monotonic; fastest bearing within 30° of the
  downwind direction when terrain is flat; toggling terrain off removes the
  upslope bias; toggling wind off makes the front near-concentric.
- Payload: `resolution_m` present; every input has `reality`; `origin.source`
  is `fixture`.
- Mode selection: patch present → `drone` default; absent → `terrain`; neither →
  shell with both disabled and reasons.
- Camera clamp: requested range below the mode minimum is clamped.
- Badge text derives from `source_resolution_m` and age, not hardcoded.
- Deep link parse: valid, unknown mode, unknown mission.
- Browser: tabs switch mode and badge; zoom does not switch mode; Terrain renders
  without a patch; reduced motion snaps growth; zero external requests.

---

## 12. Acceptance

1. Three tabs, each with a badge stating resolution and age.
2. Terrain renders a full 3D scene with **no** photogrammetry present.
3. Drone is disabled with a visible reason when there is no patch.
4. The prediction is per-bearing and visibly asymmetric downwind.
5. Toggling wind off makes the front concentric; toggling it back restores the
   asymmetry, re-animating from the origin.
6. The label states real versus fixture for every input.
7. Zero FIRMS detections at Brighton reads as coverage, not emptiness.
8. No mode switch happens on zoom.
9. The offline path works in every mode.
10. `Docs/HANDOFF.md`, `README.md` and screenshots are updated with the phase.

---

## 13. Out of scope

- Real fuel models or satellite-derived fuel moisture (fuel stays a fixture).
- Live fire perimeters from an authority (FIRMS detections are points).
- Multi-mission comparison, resources, suppression modelling.
- Regional mode for missions outside the DEM ring.
- Replacing the ODM pipeline.
