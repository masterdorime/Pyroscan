"""PyroScan server configuration and shared paths."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = Path(__file__).resolve().parent
DB_PATH = SERVER / "pyroscan.db"
WEB = ROOT / "spike" / "web"
MISSIONS = ROOT / "spike" / "missions"
CACHE = SERVER / "cache"
PROVIDERS_CACHE = CACHE / "providers"
INBOX = ROOT / "spike" / "inbox"

NODEODM = "http://127.0.0.1:3000"

# Explicit ODM options. `dsm: true` is mandatory: ODM 3.6.2 silently skips the
# DEM otherwise (found in the spike; see Docs/dashboard_design.md).
ODM_OPTIONS = [
    {"name": "use-exif", "value": True},
    {"name": "gps-accuracy", "value": 15},
    {"name": "resize-to", "value": 2000},
    {"name": "feature-quality", "value": "medium"},
    {"name": "pc-quality", "value": "medium"},
    {"name": "orthophoto-resolution", "value": 2},
    {"name": "dsm", "value": True},
    {"name": "dem-resolution", "value": 2},
]

# Cached basemap around the Brighton mission. The production path replaces this
# with a per-mission cached image.
CONTEXT = {
    "name": "Brighton Beach",
    "west": -92.0028,
    "south": 46.8367,
    "east": -91.9851,
    "north": 46.8487,
    "attribution": "Imagery © Esri, Maxar, Earthstar Geographics",
    "source": "cached offline basemap",
}

FLIGHT_PATH = [
    [0.18, 0.22], [0.38, 0.22], [0.38, 0.40], [0.18, 0.40],
    [0.18, 0.58], [0.38, 0.58], [0.38, 0.76], [0.18, 0.76],
]

STAGES = ["CAPTURE", "PHOTOGRAMMETRY", "FUSION", "SIMULATION", "ADVISORY", "DONE"]


def ensure_dirs() -> None:
    for p in (MISSIONS, CACHE, PROVIDERS_CACHE, INBOX,
              SERVER / "photogrammetry", SERVER / "pipeline"):
        p.mkdir(parents=True, exist_ok=True)
