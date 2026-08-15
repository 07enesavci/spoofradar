"""Cografi cit (geofence): tanimli bolgeye giren uçaga alarm.

Bolgeler dairesel (merkez + yaricap). Ornek: havaalanlari, yasak/askeri
sahalar. Uçak bolge icindeyse ve seyir irtifasinin altindaysa (yaklasma/
ihlal) isaretlenir.
"""

from __future__ import annotations

from dataclasses import dataclass

from opensky import Aircraft
from detectors import haversine


@dataclass
class Zone:
    name: str
    lat: float
    lon: float
    radius_km: float
    max_alt_m: float | None = None   # sadece bu irtifanin altindakilere alarm
    kind: str = "restricted"         # "airport" | "restricted" | "military"


# Ornek YASAK/ASKERI bolgeler (Turkiye). Kullanici genisletebilir.
# NOT: havaalanlari BILINCLI olarak yok — oraya inen/kalkan uçak NORMALDIR,
# "ihlal" degildir. Geofence sadece izinsiz-giris anlamli oldugu yerlerde
# (yasak saha, askeri bolge, kritik altyapi) yanlis-pozitif uretmez.
DEFAULT_ZONES = [
    # Yasak/hassas saha ornekleri (dusuk irtifada izinsiz giris supheli)
    Zone("Boğaz / İstanbul merkez (alçak uçuş)", 41.02, 29.0, 15, 800, "restricted"),
    Zone("Ankara merkez (alçak uçuş)", 39.93, 32.85, 12, 800, "restricted"),
]


@dataclass
class Breach:
    zone: str
    kind: str
    icao24: str
    callsign: str
    dist_km: float
    alt: float | None


def check_zones(current: list[Aircraft], zones=None) -> list[Breach]:
    """Bolge ihlallerini bul."""
    zones = zones or DEFAULT_ZONES
    breaches = []
    for ac in current:
        if not ac.has_position or ac.on_ground:
            continue
        for z in zones:
            d = haversine(ac.lat, ac.lon, z.lat, z.lon) / 1000.0
            if d > z.radius_km:
                continue
            if z.max_alt_m is not None and ac.baro_alt is not None \
                    and ac.baro_alt > z.max_alt_m:
                continue
            breaches.append(Breach(
                z.name, z.kind, ac.icao24, ac.callsign or "-",
                round(d, 1), ac.baro_alt,
            ))
    return breaches
