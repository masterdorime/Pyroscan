"""Rothermel (1972) surface fire spread, as used by BehavePlus/FARSITE/FlamMap.

This is the model operational tools share: Rothermel's steady rate of spread
for a surface fuel bed, with Albini's corrections, midflame wind, slope and dead
fuel moisture. It is not a coupled atmosphere model and does not model peat
smouldering, crown fire or spotting.

References:
- Rothermel 1972, INT-RP-115.
- Andrews 2018, RMRS-GTR-371 (comprehensive explanation and equations).
- Finney 1998 (FARSITE), Finney 2006 (FlamMap), Andrews 2014 (BehavePlus).
- Anderson 1983 length-to-breadth ratio.
"""
from __future__ import annotations

import math

MODEL_VERSION = "rothermel-1972.1"

# Aggregate single-class fuel beds (lb/ft2, ft, ft-1, fraction, Btu/lb).
FUELS = {
    "tropical_forest": {
        "label": "Tropical forest litter",
        "w0": 0.35, "depth": 1.5, "sigma": 1800.0, "mx": 0.25, "h": 8000.0,
    },
    "timber_litter": {
        "label": "Timber litter (FM10-like)",
        "w0": 0.46, "depth": 1.0, "sigma": 2000.0, "mx": 0.25, "h": 8000.0,
    },
    "savanna": {
        "label": "Tropical savanna grass",
        "w0": 0.12, "depth": 1.0, "sigma": 3000.0, "mx": 0.12, "h": 8000.0,
    },
    "short_grass": {
        "label": "Short grass (FM1-like)",
        "w0": 0.034, "depth": 1.0, "sigma": 3500.0, "mx": 0.12, "h": 8000.0,
    },
}
DEFAULT_FUEL = "tropical_forest"
RHO_P = 32.0          # oven-dry particle density, lb/ft3
ST = 0.0555           # total mineral content
SE = 0.01             # effective mineral content
FT_PER_M = 3.28084
M_PER_FT = 0.3048
KMH_TO_FTMIN = 54.6807
MIDFLAME = 0.4        # 10 m -> midflame wind factor (unsheltered)


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def moisture_from_weather(rh_pct: float, temp_c: float,
                          precip_mm: float = 0.0) -> float:
    """Simard (1968) equilibrium moisture, as a 1-h dead fuel fraction."""
    rh = _clamp(float(rh_pct or 60), 1.0, 100.0)
    t = float(temp_c if temp_c is not None else 25.0)
    if rh < 10:
        emc = 0.03229 + 0.281073 * rh - 0.000578 * rh * t
    elif rh < 50:
        emc = 2.22749 + 0.160107 * rh - 0.014784 * t
    else:
        emc = (21.0606 + 0.005565 * rh * rh
               - 0.00035 * rh * t - 0.483199 * rh)
    moisture = _clamp(emc / 100.0, 0.03, 0.30)
    if precip_mm and precip_mm > 0:
        moisture = min(0.30, moisture + min(0.04, 0.015 * float(precip_mm)))
    return round(moisture, 4)


def length_to_breadth(midflame_kmh: float) -> float:
    """Anderson (1983) L/B from midflame wind, clamped to 1..8."""
    u_mph = max(0.0, float(midflame_kmh) / 1.60934)
    lb = (0.936 * math.exp(0.2566 * u_mph)
          + 0.461 * math.exp(-0.1548 * u_mph) - 0.397)
    return round(_clamp(lb, 1.0, 8.0), 2)


def rate_of_spread(fuel: str, moisture: float, wind_kmh: float,
                   wind_from_deg: float, slope_deg: float,
                   aspect_deg: float = 0.0) -> dict:
    """Rothermel heading rate, m/min, plus the inputs that matter."""
    f = FUELS.get(fuel, FUELS[DEFAULT_FUEL])
    w0, depth, sigma, mx, h = (f["w0"], f["depth"], f["sigma"],
                               f["mx"], f["h"])
    mf = _clamp(float(moisture), 0.01, max(0.02, mx * 0.99))

    wn = w0 * (1 - ST)
    rho_b = w0 / max(depth, 1e-6)
    beta = rho_b / RHO_P
    beta_op = 3.348 * sigma ** -0.8189
    rel = beta / beta_op
    a = 133 * sigma ** -0.7913
    gamma_max = sigma ** 1.5 / (495 + 0.0594 * sigma ** 1.5)
    gamma = gamma_max * rel ** a * math.exp(a * (1 - rel))

    rm = _clamp(mf / mx, 0, 1)
    eta_m = max(0.0, 1 - 2.59 * rm + 5.11 * rm ** 2 - 3.52 * rm ** 3)
    eta_s = min(1.0, 0.174 * SE ** -0.19)
    i_r = gamma * wn * h * eta_m * eta_s

    xi = (math.exp((0.792 + 0.681 * math.sqrt(sigma)) * (beta + 0.1))
          / (192 + 0.2595 * sigma))
    eps = math.exp(-138 / sigma)
    qig = 250 + 1116 * mf

    midflame = max(0.0, float(wind_kmh)) * MIDFLAME
    u_ftmin = midflame * KMH_TO_FTMIN
    # BehavePlus/FARSITE wind limit; Andrews et al. recommend it not be applied,
    # but operational tools do, so we keep it explicit.
    if i_r > 0:
        u_ftmin = min(u_ftmin, 0.9 * i_r)
    c = 7.47 * math.exp(-0.133 * sigma ** 0.55)
    b = 0.02526 * sigma ** 0.54
    e = 0.715 * math.exp(-3.59e-4 * sigma)
    phi_w = c * u_ftmin ** b * rel ** -e if u_ftmin > 0 else 0.0
    tan_slope = math.tan(math.radians(_clamp(float(slope_deg), 0, 60)))
    phi_s = 5.275 * beta ** -0.3 * tan_slope ** 2

    denom = rho_b * eps * qig
    r0_ftmin = i_r * xi / denom if denom > 0 else 0.0
    r_ftmin = r0_ftmin * (1 + phi_w + phi_s)
    rate = r_ftmin * M_PER_FT

    wind_to = (float(wind_from_deg) + 180.0) % 360.0
    upslope = (float(aspect_deg) + 180.0) % 360.0
    vx = phi_w * math.sin(math.radians(wind_to)) + \
        phi_s * math.sin(math.radians(upslope))
    vy = phi_w * math.cos(math.radians(wind_to)) + \
        phi_s * math.cos(math.radians(upslope))
    bearing = (math.degrees(math.atan2(vx, vy)) % 360.0
               if (vx or vy) else wind_to)

    return {
        "rate_m_min": round(rate, 3),
        "rate_no_wind_m_min": round(r0_ftmin * M_PER_FT, 3),
        "fuel": fuel,
        "fuel_label": f["label"],
        "moisture": mf,
        "wind_kmh_10m": round(float(wind_kmh), 2),
        "midflame_kmh": round(midflame, 2),
        "bearing_deg": round(bearing, 1),
        "length_to_breadth": length_to_breadth(midflame),
        "phi_w": round(phi_w, 3),
        "phi_s": round(phi_s, 3),
        "reaction_intensity": round(i_r, 1),
        "slope_deg": round(float(slope_deg), 2),
        "model": MODEL_VERSION,
    }


def ellipse_frames(lat: float, lon: float, model: dict,
                   horizon_min: int = 360, step_min: int = 30,
                   samples: list[dict] | None = None) -> list[dict]:
    """Isochrones from the ignition at one focus, hourly wind aware."""
    m_lat = 111_320.0
    m_lon = 111_320.0 * math.cos(math.radians(lat))
    frames = []
    head_m = 0.0
    for t in range(0, horizon_min + 1, step_min):
        step = model
        if samples:
            row = samples[min(len(samples) - 1, int(round(t / 60)))]
            if row.get("model"):
                step = row["model"]
        if t > 0:
            head_m += step["rate_m_min"] * step_min
        head = head_m
        lb = max(1.0, step.get("length_to_breadth", 1.0))
        ecc = math.sqrt(max(0.0, lb * lb - 1)) / lb
        back = head * (1 - ecc) / (1 + ecc)
        a = (head + back) / 2
        c = (head - back) / 2
        b = a * math.sqrt(max(0.0, 1 - ecc * ecc))
        bearing = math.radians(step["bearing_deg"])
        ring = []
        for deg in range(0, 360, 15):
            th = math.radians(deg)
            x = c + a * math.cos(th)
            y = b * math.sin(th)
            east = x * math.sin(bearing) + y * math.cos(bearing)
            north = x * math.cos(bearing) - y * math.sin(bearing)
            ring.append([round(lon + east / m_lon, 6),
                         round(lat + north / m_lat, 6)])
        frames.append({
            "t_min": t,
            "head": {
                "lon": round(lon + head * math.sin(bearing) / m_lon, 6),
                "lat": round(lat + head * math.cos(bearing) / m_lat, 6),
            },
            "ring": ring,
            "rate_m_min": step["rate_m_min"],
            "bearing_deg": step["bearing_deg"],
            "head_m": round(head_m, 2),
        })
    return frames


def risk_from_rate(rate_m_min: float) -> str:
    if rate_m_min >= 32:
        return "CRITICAL"
    if rate_m_min >= 20:
        return "HIGH"
    if rate_m_min >= 10:
        return "MEDIUM"
    return "LOW"
