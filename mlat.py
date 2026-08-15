"""Multilateration (MLAT) — TDOA ile bagimsiz konum dogrulama.

DURUSTLUK NOTU (onemli):
  Gercek multilateration icin BIRDEN FAZLA yer alicisinin ayni sinyali
  duydugu HAM zaman-damgalari gerekir. OpenSky anonim /states/all bunu VERMEZ.
  Ham veri iki yoldan gelir:
    1. Kendi RTL-SDR alici aginiz (2+ istasyon, GPS-senkron saat)
    2. OpenSky Impala/Trino akademik erisim (ham time_of_day per alici)

  Bu modul GERCEK TDOA cozucusunu icerir — matematik dogru ve calisir.
  Alici verisi verilirse emitter konumunu bagimsiz hesaplar. Konum ADS-B
  iddiasiyla uyusmazsa = KANITLANMIS spoofing (süphe degil).

  Ham veri yokken: OpenSky bazi uçaklari ZATEN MLAT'lamis (position_source==2).
  cross_check() o durumda ADS-B-iddia vs MLAT-konum tutarliligina bakar.

Matematik:
  Alici i, emitter x'i t_i aninda duyar. Menzil farki:
    |x - p_i| - |x - p_0| = c * (t_i - t_0)
  Bu hiperbolik denklem sistemi. Gauss-Newton en-kucuk-kareler ile x cozulur.
  Koordinatlar ECEF (dunya-merkezli), sonra lat/lon/alt'a cevrilir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

try:
    import numpy as np
    _HAS_NUMPY = True
except Exception:
    _HAS_NUMPY = False

C = 299_792_458.0            # isik hizi m/s
WGS84_A = 6_378_137.0        # dunya ekvator yaricapi
WGS84_E2 = 6.694379990e-3    # birinci eksantriklik karesi


# --- Koordinat donusumleri (WGS84 <-> ECEF) --------------------------------
def geodetic_to_ecef(lat_deg, lon_deg, alt_m):
    """Lat/lon/irtifa -> ECEF (x,y,z) metre."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + alt_m) * cos_lat * math.cos(lon)
    y = (n + alt_m) * cos_lat * math.sin(lon)
    z = (n * (1 - WGS84_E2) + alt_m) * sin_lat
    return x, y, z


def ecef_to_geodetic(x, y, z):
    """ECEF -> lat/lon/irtifa (Bowring iteratif)."""
    lon = math.atan2(y, x)
    p = math.sqrt(x * x + y * y)
    lat = math.atan2(z, p * (1 - WGS84_E2))
    for _ in range(6):
        sin_lat = math.sin(lat)
        n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
        alt = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - WGS84_E2 * n / (n + alt)))
    sin_lat = math.sin(lat)
    n = WGS84_A / math.sqrt(1 - WGS84_E2 * sin_lat * sin_lat)
    alt = p / math.cos(lat) - n
    return math.degrees(lat), math.degrees(lon), alt


@dataclass
class Receiver:
    """Yer alicisi: konum + sinyali duydugu zaman."""
    lat: float
    lon: float
    alt: float
    t_arrival: float   # varis zamani (saniye, yuksek cozunurluk)


@dataclass
class MlatResult:
    lat: float
    lon: float
    alt: float
    residual_m: float       # cozum kalitesi (dusuk = iyi)
    receivers_used: int
    converged: bool


def solve_tdoa(receivers: list[Receiver], alt_hint: float | None = None,
               max_iter: int = 30) -> MlatResult | None:
    """N alicinin varis zamanlarindan emitter konumunu coz (TDOA/MLAT).

    En az 4 alici gerekir (3B konum icin). irtifa ipucu varsa 3 alici yeter.
    Gauss-Newton en-kucuk-kareler; ECEF uzayinda coz, lat/lon/alt'a cevir.
    """
    if not _HAS_NUMPY:
        return None
    n_rx = len(receivers)
    min_rx = 3 if alt_hint is not None else 4
    if n_rx < min_rx:
        return None

    # Alici konumlari ECEF
    rx = np.array([geodetic_to_ecef(r.lat, r.lon, r.alt) for r in receivers])
    times = np.array([r.t_arrival for r in receivers])

    # Referans = en erken duyan alici
    ref = int(np.argmin(times))
    # Menzil farklari: c * (t_i - t_ref)
    range_diff = C * (times - times[ref])

    # Baslangic tahmini: alicilarin agirlik merkezi, biraz yukarida
    x = rx.mean(axis=0).astype(float)
    x[2] += 8000  # ~seyir irtifasi tohum

    for _ in range(max_iter):
        # Her aliciya mesafe
        d = np.linalg.norm(rx - x, axis=1)
        d_ref = d[ref]
        # Model menzil farki vs olculen
        f = (d - d_ref) - range_diff
        # Jacobian: d/dx [ |x-p_i| - |x-p_ref| ]
        with np.errstate(divide="ignore", invalid="ignore"):
            u = (x - rx) / d[:, None]           # birim vektorler
            u_ref = (x - rx[ref]) / d_ref
        J = u - u_ref                            # (n_rx, 3)

        # irtifa ipucu varsa ek kisit (z'yi sabitle egilimi)
        rows = [J]
        res = [f]
        if alt_hint is not None:
            # emitter'in ECEF |x| ~ dunya yaricapi + irtifa
            target_r = WGS84_A + alt_hint
            cur_r = np.linalg.norm(x)
            grad_r = x / cur_r
            rows.append(grad_r[None, :] * 1e-3)   # yumusak agirlik
            res.append(np.array([(cur_r - target_r) * 1e-3]))

        Jf = np.vstack(rows)
        ff = np.concatenate(res)
        try:
            dx, *_ = np.linalg.lstsq(Jf, -ff, rcond=None)
        except np.linalg.LinAlgError:
            return MlatResult(0, 0, 0, 9e9, n_rx, False)
        x = x + dx
        if np.linalg.norm(dx) < 1.0:      # 1 metre altinda yakinsadi
            break

    # Kalinti (cozum kalitesi)
    d = np.linalg.norm(rx - x, axis=1)
    residual = float(np.sqrt(np.mean(((d - d[ref]) - range_diff) ** 2)))
    lat, lon, alt = ecef_to_geodetic(*x)
    converged = residual < 5000  # 5 km kalinti altinda kabul
    return MlatResult(lat, lon, alt, residual, n_rx, converged)


# --- Canli caprazkontrol (ham veri yokken) ---------------------------------
def cross_check(ac, mlat_lat: float, mlat_lon: float,
                max_disagree_km: float = 15.0) -> dict:
    """ADS-B iddia edilen konum vs bagimsiz MLAT konumu.

    Uyusmazlik buyukse = KANITLANMIS spoof (uçak yalan konum yayinliyor,
    ama bagimsiz uçgenleme onu baska yerde buluyor).
    """
    from detectors import haversine
    if not ac.has_position:
        return {"checked": False}
    d_km = haversine(ac.lat, ac.lon, mlat_lat, mlat_lon) / 1000.0
    spoof = d_km > max_disagree_km
    return {
        "checked": True,
        "disagree_km": round(d_km, 1),
        "spoof_confirmed": spoof,
        "verdict": ("🔴 KANITLANMIŞ SPOOF" if spoof else "🟢 MLAT doğruladı"),
        "detail": (f"ADS-B iddiası ile bağımsız MLAT konumu {d_km:.0f} km "
                   "farklı — uçak yalan konum yayınlıyor."
                   if spoof else
                   f"ADS-B konumu MLAT ile uyumlu ({d_km:.1f} km fark)."),
    }
