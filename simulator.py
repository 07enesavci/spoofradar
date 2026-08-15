"""Spoof simulatoru / demo modu.

Gercek trafige SAHTE uçak enjekte eder ki tespit motoru canli gosterilebilsin.
Sunum/demo icin: gercek spoofing beklemeden 'bak, aninda yakaliyor' denir.

Uretilen senaryolar (icao24 'SIM' ile baslar, kolay ayirt edilir):
  - teleport: iki snapshot arasi imkansiz sicrama (impossible_speed tetikler)
  - ghost: gerçekci ama var olmayan hayalet uçak
  - clone: mevcut bir uçagin ICAO'sunu kopyalayip uzaga koy (duplicate_icao)
  - drift: yavas, fizik-ihlali olmayan sapma (ML/fingerprint tetikler)
"""

from __future__ import annotations

import math
import random
import time

from opensky import Aircraft


def _mk(icao, cs, lat, lon, alt, vel, track, t, squawk="1200",
        vr=0.0, geo=None, src=0, country="SIMULATION") -> Aircraft:
    return Aircraft(
        icao24=icao, callsign=cs, country=country,
        lon=lon, lat=lat, baro_alt=alt, geo_alt=geo if geo is not None else alt,
        on_ground=False, velocity=vel, track=track, vertical_rate=vr,
        squawk=squawk, timestamp=t, position_source=src,
    )


def inject(current: list[Aircraft], prev_by_icao: dict,
           scenarios: list[str], center=(39.0, 33.0)) -> list[Aircraft]:
    """Secili senaryolara gore sahte uçaklari uret + prev'e tohum ekle.

    Donen liste 'current'a eklenir. prev_by_icao yerinde guncellenir ki
    teleport/clone gibi ardisik-karsilastirma kurallari tetiklensin.
    """
    t = time.time()
    clat, clon = center
    fakes = []

    if "teleport" in scenarios:
        icao = "sim01"
        # onceki konumu merkeze koy; simdi 500 km uzaga isinla
        prev_by_icao[icao] = _mk(icao, "SPOOF1", clat, clon, 10000, 250, 90, t - 12)
        fakes.append(_mk(icao, "SPOOF1", clat + 4.5, clon, 10000, 250, 90, t))

    if "ghost" in scenarios:
        icao = "sim02"
        fakes.append(_mk(icao, "GHOST1",
                         clat + random.uniform(-1, 1), clon + random.uniform(-1, 1),
                         9000, 240, random.randint(0, 359), t, geo=None))

    if "clone" in scenarios and current:
        victim = next((a for a in current if a.has_position), None)
        if victim:
            # ayni ICAO, cok uzak konumda = duplicate_icao
            fakes.append(_mk(victim.icao24, victim.callsign or "CLONE",
                             victim.lat + 3.0, victim.lon + 3.0,
                             victim.baro_alt or 10000, 250, 180, t))

    if "drift" in scenarios:
        icao = "sim04"
        # Fizik-ihlali YOK: konum 12s'de ~3km (250 m/s ile tutarli) hareket eder,
        # ama BILDIRILEN hiz 330 m/s (konumla celisir). Sert kural tetiklemez;
        # verify (hiz-konum tutarsizligi) ve zamanla fingerprint yakalar.
        prev_by_icao[icao] = _mk(icao, "DRIFT1", clat - 1.0, clon - 1.0, 11000, 1400, 45, t - 12)
        fakes.append(_mk(icao, "DRIFT1", clat - 0.98, clon - 0.98, 11000, 1400, 45, t))

    if "emergency" in scenarios:
        icao = "sim05"
        fakes.append(_mk(icao, "MAYDAY1", clat + 0.5, clon + 0.5, 6000, 200, 270, t,
                         squawk="7700"))

    return fakes


# --- Cevrimdisi demo: sentetik NORMAL trafik ------------------------------
# Internet/OpenSky yoksa bile dashboard calissin diye gercekci filo uretir.
# Mulakat/sunum icin kritik: baglanti kopsa da tespit motoru gosterilir.
_DEMO_AIRLINES = [
    ("THY", "Turkey"), ("PGT", "Turkey"), ("SXS", "Turkey"), ("KKK", "Turkey"),
    ("DLH", "Germany"), ("AFR", "France"), ("UAE", "United Arab Emirates"),
    ("QTR", "Qatar"), ("RYR", "Ireland"), ("EZY", "United Kingdom"),
    ("SWR", "Switzerland"), ("AZA", "Italy"),
]
_ALT_LEVELS = [9000, 9500, 10000, 10500, 11000, 11600, 12000]

# bbox anahtari -> filo (yerinde ilerletilir; her cagri konumlari tazeler)
_demo_fleets: dict[tuple, list[dict]] = {}


def generate_normal_traffic(bbox, n: int = 45) -> list[Aircraft]:
    """Sentetik ama gercekci normal trafik anlik goruntusu.

    Ayni filo cagrilar arasi KORUNUR ve her cagrida hiz*sure kadar ilerler —
    boylece harita blipleri hareket eder ve rota izi (tracks) olusur. bbox
    kenarina carpinca yon 'seker' (icerde kalir). icao24 'demo' ile baslar.
    """
    if not bbox:
        bbox = (35.0, 25.0, 43.0, 45.0)
    lamin, lomin, lamax, lomax = bbox
    key = tuple(round(x, 3) for x in bbox) + (n,)
    now = time.time()

    fleet = _demo_fleets.get(key)
    if fleet is None:
        rng = random.Random(hash(key) & 0xFFFFFFFF)
        fleet = []
        for i in range(n):
            al, ctry = rng.choice(_DEMO_AIRLINES)
            fleet.append({
                "icao": f"demo{i:03d}",
                "cs": f"{al}{rng.randint(100, 999)}",
                "country": ctry,
                "lat": rng.uniform(lamin + 0.3, lamax - 0.3),
                "lon": rng.uniform(lomin + 0.3, lomax - 0.3),
                "track": rng.uniform(0, 359),
                "vel": rng.uniform(180, 260),
                "alt": rng.choice(_ALT_LEVELS),
                "t": now,
            })
        _demo_fleets[key] = fleet

    out = []
    for f in fleet:
        dt = min(now - f["t"], 30.0)   # ilk kare / uzun bekleme sicramasin
        f["t"] = now
        dist = f["vel"] * dt           # metre
        rad = math.radians(f["track"])
        f["lat"] += (dist * math.cos(rad)) / 111320.0
        cosl = math.cos(math.radians(f["lat"])) or 1e-6
        f["lon"] += (dist * math.sin(rad)) / (111320.0 * cosl)
        # kenara carpinca iceri don
        if f["lat"] <= lamin + 0.1 or f["lat"] >= lamax - 0.1:
            f["track"] = (180 - f["track"]) % 360
            f["lat"] = min(max(f["lat"], lamin + 0.15), lamax - 0.15)
        if f["lon"] <= lomin + 0.1 or f["lon"] >= lomax - 0.1:
            f["track"] = (360 - f["track"]) % 360
            f["lon"] = min(max(f["lon"], lomin + 0.15), lomax - 0.15)
        out.append(_mk(f["icao"], f["cs"], f["lat"], f["lon"], f["alt"],
                       f["vel"], f["track"], now, geo=f["alt"],
                       country=f["country"]))
    return out


SCENARIO_LABELS = {
    "teleport": "🚀 Işınlanma (imkansız hız)",
    "ghost": "👻 Hayalet uçak",
    "clone": "👥 Klon kimlik",
    "drift": "📈 Yavaş sapma (ML/fingerprint)",
    "emergency": "🚨 Acil durum kodu (7700)",
}
