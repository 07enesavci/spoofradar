"""ADS-B anomali / spoofing tespit kurallari.

Her uçagin ardisik iki snapshot'i karsilastirilir. Fiziksel olarak
imkansiz veya süpheli gecisler flaglanir. Bu ilk surumde kural-tabanli
(rule-based) tespit var; ML katmani sonra eklenecek.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from opensky import Aircraft

# --- Fiziksel limitler (esikler) -------------------------------------------
MAX_SPEED_MS = 350.0        # ~1260 km/s. Ticari jet ~250 m/s. Ustu süpheli.
MAX_ALT_JUMP_M = 1500.0     # iki snapshot arasi makul irtifa degisimi
MIN_DT = 0.5                # cok kucuk zaman farkini yoksay (bolme hatasi)
EARTH_R = 6_371_000.0       # metre


@dataclass
class Alert:
    icao24: str
    callsign: str
    kind: str          # anomali tipi
    detail: str        # insan-okur aciklama
    severity: str      # "low" | "med" | "high"


def haversine(lat1, lon1, lat2, lon2) -> float:
    """Iki koordinat arasi mesafe (metre)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def check_impossible_speed(prev: Aircraft, cur: Aircraft) -> Alert | None:
    """Konum siçramasi ima edilen hiz fiziksel limiti asiyor mu?"""
    if not (prev.has_position and cur.has_position):
        return None
    dt = cur.timestamp - prev.timestamp
    if dt < MIN_DT:
        return None
    dist = haversine(prev.lat, prev.lon, cur.lat, cur.lon)
    implied = dist / dt  # m/s
    if implied > MAX_SPEED_MS:
        return Alert(
            cur.icao24, cur.callsign, "impossible_speed",
            f"{implied*3.6:.0f} km/s ima edildi ({dist/1000:.0f} km / {dt:.0f} s). "
            f"Limit {MAX_SPEED_MS*3.6:.0f} km/s. Isinlanma = spoofing süphesi.",
            "high",
        )
    return None


def check_altitude_jump(prev: Aircraft, cur: Aircraft) -> Alert | None:
    """Ani irtifa siçramasi."""
    if prev.baro_alt is None or cur.baro_alt is None:
        return None
    dt = cur.timestamp - prev.timestamp
    if dt < MIN_DT:
        return None
    jump = abs(cur.baro_alt - prev.baro_alt)
    if jump > MAX_ALT_JUMP_M:
        return Alert(
            cur.icao24, cur.callsign, "altitude_jump",
            f"Irtifa {jump:.0f} m degisti ({dt:.0f} s icinde). Ani sicrama.",
            "med",
        )
    return None


# Uluslararasi acil durum transponder kodlari
EMERGENCY_SQUAWK = {
    "7500": "Uçak kaçırma (hijack)",
    "7600": "Telsiz arızası (radio failure)",
    "7700": "Genel acil durum (emergency)",
}


def check_emergency_squawk(cur: Aircraft) -> Alert | None:
    """Acil durum squawk kodu (7500/7600/7700)."""
    if cur.squawk in EMERGENCY_SQUAWK:
        return Alert(
            cur.icao24, cur.callsign, "emergency_squawk",
            f"ACİL KOD {cur.squawk}: {EMERGENCY_SQUAWK[cur.squawk]}.",
            "high",
        )
    return None


def check_bad_callsign(cur: Aircraft) -> Alert | None:
    """Bos veya bozuk çagri isareti (spoof'ta sik gorulur)."""
    cs = cur.callsign
    if cs and any(c for c in cs if not (c.isalnum() or c == " ")):
        return Alert(
            cur.icao24, cur.callsign, "malformed_callsign",
            f"Cagri isaretinde gecersiz karakter: '{cs}'.",
            "low",
        )
    return None


def find_duplicate_icao(current: list[Aircraft]) -> list[Alert]:
    """Ayni ICAO24 birden fazla konumda = klonlanmis kimlik."""
    seen: dict[str, Aircraft] = {}
    alerts: list[Alert] = []
    for ac in current:
        if not ac.icao24 or not ac.has_position:
            continue
        if ac.icao24 in seen:
            other = seen[ac.icao24]
            d = haversine(ac.lat, ac.lon, other.lat, other.lon)
            if d > 5000:  # 5 km'den uzak iki "ayni" uçak
                alerts.append(Alert(
                    ac.icao24, ac.callsign, "duplicate_icao",
                    f"Ayni ICAO24 iki uzak konumda ({d/1000:.0f} km). Klon kimlik.",
                    "high",
                ))
        else:
            seen[ac.icao24] = ac
    return alerts


# Ardisik snapshot'lara uygulanan kurallar
PAIR_RULES = [check_impossible_speed, check_altitude_jump]
# Tek uçaga uygulanan kurallar
SINGLE_RULES = [check_bad_callsign, check_emergency_squawk]


def analyze(prev_by_icao: dict[str, Aircraft],
            current: list[Aircraft]) -> list[Alert]:
    """Bir snapshot'i onceki durumla karsilastirip tum alarmlari uretir."""
    alerts: list[Alert] = []

    for ac in current:
        for rule in SINGLE_RULES:
            a = rule(ac)
            if a:
                alerts.append(a)

        prev = prev_by_icao.get(ac.icao24)
        if prev:
            for rule in PAIR_RULES:
                a = rule(prev, ac)
                if a:
                    alerts.append(a)

    alerts.extend(find_duplicate_icao(current))
    return alerts
