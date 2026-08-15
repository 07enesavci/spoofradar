"""Olay tespiti: karanlik uçak + yakinlasma/cakisma.

- Karanlik uçak (signal dropout): onceki turda seyir irtifasinda gorunen ama
  bu turda ANIDEN kaybolan uçak. Transponder kapatma = kacis/gizlenme isareti
  (bbox disina cikmayi ayirt etmek icin kenar payi birakilir).
- Yakinlasma (TCAS-benzeri): iki uçak yatay+dikey olarak tehlikeli yakin.
"""

from __future__ import annotations

from dataclasses import dataclass

from opensky import Aircraft
from detectors import haversine

# Karanlik uçak esikleri
DARK_MIN_ALT = 4000.0       # sadece seyir irtifasindaki kayiplar (yerde inis degil)
EDGE_MARGIN = 0.4           # bbox kenarina bu kadar yakinsa "cikti" say (derece)

# Yakinlasma esikleri (kaba TCAS)
CONFLICT_HORIZ_M = 9260.0   # 5 deniz mili
CONFLICT_VERT_M = 300.0     # ~1000 ft


@dataclass
class Event:
    kind: str       # "dark" | "conflict"
    icao24: str
    detail: str
    lat: float | None = None
    lon: float | None = None


def find_dark(prev_by_icao: dict[str, Aircraft],
              current: list[Aircraft],
              bbox=None) -> list[Event]:
    """Onceki turda olup bu turda kaybolan seyir uçaklari."""
    cur_ids = {a.icao24 for a in current}
    events = []
    for icao, p in prev_by_icao.items():
        if icao in cur_ids:
            continue
        if p.on_ground or p.baro_alt is None or p.baro_alt < DARK_MIN_ALT:
            continue
        if not p.has_position:
            continue
        # bbox kenarina yakinsa muhtemelen sadece cikti, karanlik sayma
        if bbox:
            lamin, lomin, lamax, lomax = bbox
            if (p.lat < lamin + EDGE_MARGIN or p.lat > lamax - EDGE_MARGIN or
                    p.lon < lomin + EDGE_MARGIN or p.lon > lomax - EDGE_MARGIN):
                continue
        events.append(Event(
            "dark", icao,
            f"Sinyal kesildi: {p.callsign or icao} {p.baro_alt:.0f} m'de "
            "aniden kayboldu (transponder kapatma?).",
            p.lat, p.lon,
        ))
    return events


def find_conflicts(current: list[Aircraft]) -> list[Event]:
    """Tehlikeli yakinlasan uçak ciftleri (kaba TCAS)."""
    air = [a for a in current if a.has_position and not a.on_ground
           and a.baro_alt is not None and a.baro_alt > 2000]
    events = []
    seen = set()
    for i in range(len(air)):
        for j in range(i + 1, len(air)):
            a, b = air[i], air[j]
            vert = abs(a.baro_alt - b.baro_alt)
            if vert > CONFLICT_VERT_M:
                continue
            horiz = haversine(a.lat, a.lon, b.lat, b.lon)
            if horiz > CONFLICT_HORIZ_M:
                continue
            key = tuple(sorted((a.icao24, b.icao24)))
            if key in seen:
                continue
            seen.add(key)
            # NOT: bu bir YAKINLIK olcumu, cakisma tahmini DEGIL. Uçaklarin
            # yaklasip yaklasmadigini, ATC izni olup olmadigini bilmez.
            # Havaalani yaklasmasinda dusuk ayrim normaldir. "Bilgi" olarak sun.
            events.append(Event(
                "conflict", a.icao24,
                f"Yakın geçiş (bilgi): {a.callsign or a.icao24} ↔ "
                f"{b.callsign or b.icao24}  yatay {horiz/1852:.1f} nm, "
                f"dikey {vert:.0f} m. (ICAO ayrım-minimumu altı — havaalanı "
                "yaklaşmasında normal olabilir.)",
                (a.lat + b.lat) / 2, (a.lon + b.lon) / 2,
            ))
    return events
