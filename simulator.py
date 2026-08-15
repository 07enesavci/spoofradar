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

import random
import time

from opensky import Aircraft


def _mk(icao, cs, lat, lon, alt, vel, track, t, squawk="1200",
        vr=0.0, geo=None, src=0) -> Aircraft:
    return Aircraft(
        icao24=icao, callsign=cs, country="SIMULATION",
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


SCENARIO_LABELS = {
    "teleport": "🚀 Işınlanma (imkansız hız)",
    "ghost": "👻 Hayalet uçak",
    "clone": "👥 Klon kimlik",
    "drift": "📈 Yavaş sapma (ML/fingerprint)",
    "emergency": "🚨 Acil durum kodu (7700)",
}
