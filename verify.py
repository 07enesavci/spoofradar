"""Çok-sinyal capraz dogrulama.

DURUSTLUK NOTU: Gercek multilateration (coklu-alici uçgenlemesi) icin her
alicinin ham zaman-damgasi gerekir; OpenSky ucretsiz/anonim /states/all bunu
VERMEZ. Onun yerine ELDEKI sinyalleri capraz kontrol ederiz — tutarsizlik
spoofing'in izidir:

  1. Hiz-vektor tutarliligi: bildirilen hiz*dt, gercek konum-deltasi ile
     uyusuyor mu? (spoofer konum ziplatinca uyusmaz)
  2. Yon (track) vs gercek gidis acisi (bearing): uyusuyor mu?
  3. Baro-geo irtifa sapmasi (GNSS bozulmasi)
  4. position_source: MLAT (2) = konum zaten bagimsiz uçgenlendi = spoof zor

Sonuc: LIKELY_REAL / SUSPECT / LIKELY_SPOOF + gerekce listesi.
Bu, "süphe"yi coklu-kanit ile guclendirir; kesin degil ama savunulabilir.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from opensky import Aircraft
from detectors import haversine


@dataclass
class Verdict:
    icao24: str
    status: str            # "LIKELY_REAL" | "SUSPECT" | "LIKELY_SPOOF"
    confidence: int        # 0-100 (gercek olma güveni)
    reasons: list[str] = field(default_factory=list)


def bearing(lat1, lon1, lat2, lon2) -> float:
    """Iki nokta arasi gidis acisi (derece, kuzeyden saat yonu)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def angle_diff(a, b) -> float:
    """Iki aci arasi en kucuk fark (0-180)."""
    d = abs((a - b) % 360)
    return min(d, 360 - d)


def verify(prev: Aircraft | None, cur: Aircraft) -> Verdict:
    """Bir uçagi mevcut + onceki durumla capraz dogrula."""
    conf = 100
    reasons = []

    # 4. MLAT bonusu (bagimsiz uçgenleme)
    if cur.position_source == 2:
        reasons.append("✓ MLAT ile konumlandı (bağımsız doğrulama)")
    # 3. baro-geo sapmasi
    if cur.baro_alt is not None and cur.geo_alt is None and not cur.on_ground:
        conf -= 15
        reasons.append("⚠ GNSS irtifası yok (zayıf sinyal / jamming)")
    elif (cur.baro_alt is not None and cur.geo_alt is not None
          and abs(cur.geo_alt - cur.baro_alt) > 1200):
        conf -= 15
        reasons.append(f"⚠ Baro-GNSS sapması {abs(cur.geo_alt-cur.baro_alt):.0f} m")

    if prev is not None and prev.has_position and cur.has_position:
        dt = cur.timestamp - prev.timestamp
        if dt > 0.5:
            dist = haversine(prev.lat, prev.lon, cur.lat, cur.lon)
            implied = dist / dt  # m/s

            # 1. hiz-vektor tutarliligi
            if cur.velocity is not None and cur.velocity > 20:
                ratio = implied / cur.velocity if cur.velocity else 99
                if ratio > 3 or ratio < 0.2:
                    conf -= 45
                    reasons.append(
                        f"✗ Hız tutarsız: bildirilen {cur.velocity*3.6:.0f} km/s, "
                        f"konumdan {implied*3.6:.0f} km/s")
                else:
                    reasons.append("✓ Hız-konum tutarlı")

            # 2. yon (track) vs gercek bearing
            if cur.track is not None and dist > 200:
                brg = bearing(prev.lat, prev.lon, cur.lat, cur.lon)
                ad = angle_diff(cur.track, brg)
                if ad > 60:
                    conf -= 30
                    reasons.append(
                        f"✗ Yön tutarsız: track {cur.track:.0f}°, "
                        f"gerçek gidiş {brg:.0f}° (fark {ad:.0f}°)")
                else:
                    reasons.append("✓ Yön-rota tutarlı")

    conf = max(0, min(100, conf))
    if conf >= 75:
        status = "LIKELY_REAL"
    elif conf >= 45:
        status = "SUSPECT"
    else:
        status = "LIKELY_SPOOF"
    return Verdict(cur.icao24, status, conf, reasons)


VERDICT_LABEL = {
    "LIKELY_REAL": "🟢 Muhtemelen gerçek",
    "SUSPECT": "🟡 Şüpheli",
    "LIKELY_SPOOF": "🔴 Muhtemelen sahte (spoof)",
}
