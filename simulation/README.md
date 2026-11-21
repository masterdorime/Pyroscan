# PyroScan 3D Payload Studio

An interactive simulation of the PyroScan drone payload. A single self-contained HTML file: the 3D models, three.js, and the scene all run from one document you can open by double-clicking.

**Open:** `pyroscan_payload_studio.html`

---

## Why there is a build step

`file://` blocks `fetch` for `.glb` files sitting next to the document (CORS). The three models therefore have to travel inside the document as base64, and injecting ~1.8 MB of base64 by hand is not reasonable.

```
assets/*.glb          source models (archive, not read at runtime)
src/studio.html       template + __B64_* placeholders
build.py              injects base64 → one output file
pyroscan_payload_studio.html   ← the result, this is what you open
```

```powershell
python simulation/build.py
```

The build fails hard if a placeholder is left unreplaced or an asset is missing. Do not edit the output file — edit `src/studio.html` and rebuild.

---

## Deep links

Useful for sharing a specific view, and used for automated screenshots.

| Parameter | Values | Effect |
|---|---|---|
| `view` | `free` `payload` `posko` `laptop` `follow` `nadir` | Camera position |
| `exploded` | `1` | Exploded view |
| `sim` | `1` | Start the flight simulation immediately |
| `tab` | `sim` `inspect` `telemetry` | Right-hand panel tab |
| `debug` | `1` | Diagnostic panel: nearest meshes, radius, parent |

Example: `...html?view=payload&exploded=1`

---

## 3D assets

| Model | Used for | Treatment |
|---|---|---|
| `drone_low_poly.glb` | Drone frame | Bbox-normalised; rotor blur derived from `Cylinder*` nodes |
| `smartphone.glb` | Camera payload (Realme 3 Pro) | Hung below the frame, visible through the tray opening |
| `esp32.glb` | Radio module | Rotated out of Z-up, placed on the tray edge |

Everything goes through `fitObject()`: detect the flat axis → rotate to Y-up → uniform scale → centre at origin. There are no hardcoded rotation values, so swapping in a different model still fits.

If one model fails to parse, that part **falls back to the procedural primitives** and the status indicator in the bottom right reports how many failed. The scene never breaks entirely.

---

## Implementation notes

A few things that are invisible on screen but determine the result:

- **`renderer.outputEncoding = sRGB` + ACES.** Without sRGB, GLB textures look washed out. But once sRGB is on, procedural hexadecimal colours (written in sRGB) must be converted to linear — otherwise the whole scene turns milky white. `tuneSceneMaterials()` handles that, before the GLB models are added.
- **`scene.environment`** lights every `MeshStandardMaterial`. Its intensity is lowered to 0.22 for the scene and 1.15 for GLB models only.
- **Waypoint markers** are now a single `Points` cloud. Previously they were 14 spheres of `r=0.25`, and the first one sat exactly at the drone position, so it read as a ball hanging off the payload.
- **Fire particles** need a `map`; `PointsMaterial` without a texture renders squares.
- **The scan volume** uses a vertical alpha gradient. A solid cone makes a camera inside it read the nearest wall as a hard disc.
- **The contact shadow** is raycast onto the terrain every frame, so it does not float above a hill.

---

## Verification

There are no automated visual tests. What is used:

```powershell
npx playwright screenshot --channel=msedge --viewport-size="1600,900" `
  --wait-for-timeout=9000 "file:///C:/.../pyroscan_payload_studio.html?view=payload" `
  "simulation/shots/check.png"
```

The asset status in the bottom right is the primary indicator: `ASET 3D: 3/3 · 21.682 TRIANGLES` means all three models loaded. If it shows `ERROR: ...`, open `?debug=1` to list the meshes nearest the payload.

Reference screenshots are in `shots/`.

---

## Differences from the original file

Original: `C:\Users\TRISTAN\Downloads\interactive_3d_simulation_environment.html` (unchanged).

What changed: three procedural objects → GLB models, solid tray → frame with a camera opening, colour pipeline fixed, scan volume + footprint + contact shadow + colliding rotor blur added, fire particles fixed, and the `WebODM`/`NNAPI`/`915 MHz` text aligned with PRD v1.3.1.
