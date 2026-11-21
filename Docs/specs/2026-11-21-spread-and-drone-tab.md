# PyroScan — Spread Model v2 and the Drone Tab Plan

**Date:** 2026-11-21
**Status:** spread v2 implemented for fire sites; drone tab is a plan, not built.

## 1. What operational tools use

| Tool | Spread model |
|---|---|
| BehavePlus | Rothermel (1972), Albini corrections |
| FARSITE | Rothermel + Huygens ellipse growth, time-varying wind/fuel moisture |
| FlamMap / IFTDSS | Rothermel; Minimum Travel Time (MTT), static weather |
| WRF-SFIRE / ELMFIRE / CAWFE | Rothermel (or similar) coupled to atmosphere / level set |
| Prometheus | Canadian Forest Fire Behavior Prediction (FBP), empirical |
| PHOENIX RapidFire | Empirical Australian model |
| Australis / Spark | Empirical / hybrid |

There is no single “accurate” model. Empirical models are fast and operational;
coupled fire-atmosphere models are physically richer but expensive and rarely
used for tactical forecasts. Rothermel is the common surface-fire core of the
US tools, and it is what we implemented.

Sources:
- Andrews 2018, RMRS-GTR-371 — Rothermel equations and corrections.
- Rothermel 1972, INT-RP-115.
- Finney 1998 (FARSITE), Finney 2006 (FlamMap).
- IFTDSS/WFDSS model comparison (FlamMap/MTT/FARSITE).
- Australian simulator evaluation (Phoenix, Prometheus, Spark, Australis).
- Reviews of coupled fire-atmosphere models (WRF-SFIRE, CAWFE, ForeFire).

## 2. Implementation

`server/pipeline/rothermel.py`:

- Rothermel heading rate in m/min: reaction intensity, propagating flux,
  wind factor, slope factor, heat sink, wind limit.
- Single aggregate surface fuel class per fuel model (tropical forest litter,
  timber litter, savanna, short grass). Load, depth, SAV, moisture of
  extinction and heat content are explicit.
- Dead 1-h fuel moisture from Simard (1968) equilibrium moisture using RH and
  temperature, with a precipitation adjustment.
- Midflame wind = 0.4 × 10 m wind; hourly Open-Meteo forecast (temperature,
  RH, wind speed/direction, precipitation).
- Slope from the site DEM; bearing is the vector sum of wind and upslope.
- Anderson (1983) length-to-breadth ratio; ellipse isochrones with the ignition
  at the rear focus; head distance integrates the hourly rate (not rate × total
  time), 30-minute steps over 6 hours.
- `risk_from_rate` reuses the dashboard thresholds.

The site API and UI already consume the frames: strip charts, isochrone rings,
head marker, risk/rate, fuel and moisture in the strip header.

## 3. Honest limits

- The fuel model is a **single aggregate class**, not a per-pixel fuel map.
  No Indonesian fuel-type layer is bundled.
- **Peat smouldering is not modelled** by Rothermel; the default tropical
  forest litter is a surface-fire assumption.
- No crown fire, spotting, live fuel moisture, or coupled atmosphere.
- The model is **not calibrated or validated** against Indonesian fire
  perimeters. It is a standard model with explicit inputs, not an operational
  forecast.
- The site window is 18 km; the spread runs over 6 hours as an ellipse series,
  not a Huygens perimeter union.

These limits are printed in the UI (fuel/moisture/model) and must not be hidden.

## 4. Drone tab plan (point 3)

The existing `Drone` tab becomes the payload/photogrammetry home, not a new
page:

- **Peripheral**: pair/select the phone payload, show battery, storage, GNSS
  and Camera2 level; offline.
- **Upload**: drag/drop or folder import of JPEGs into a per-site inbox; one
  folder per site/mission; EXIF GPS required.
- **Photogrammetry**: create a site mission, queue NodeODM (existing door),
  stream progress, then open the textured mesh in Drone mode.
- **Honesty**: with no photos, the tab states `no survey at this detection` and
  the recon action is disabled. No fake mesh.
- Contracts: do not change `server/db.py` schema or the NodeODM interface
  without the owner; the site mission is an ordinary mission with a site bbox.

Not built yet. The fire-site view currently stops at terrain + imagery + spread.
