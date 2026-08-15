"""OpenSky Network istemcisi.

Canlı ADS-B durum vektörlerini halka açık OpenSky API'sinden çeker.
Kimlik doğrulama gerekmez (anonim kullanım rate-limitli: ~400 istek/gün).
Belirli bir cografi kutu (bounding box) verilebilir.

Durum vektörü alanları (OpenSky REST dokümanı):
  0 icao24        benzersiz uçak adresi (hex)
  1 callsign      çağrı işareti
  2 origin_country
  5 longitude
  6 latitude
  7 baro_altitude (m)
  8 on_ground     (bool)
  9 velocity      (m/s)
  10 true_track   (derece)
  11 vertical_rate (m/s)
  13 geo_altitude (m)
  14 squawk
  16 position_source
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests

OPENSKY_URL = "https://opensky-network.org/api/states/all"

# Opsiyonel kimlik dogrulama: ortam degiskeni verilirse kullanilir.
# Ucretsiz OpenSky hesabi = 4000 kredi/gun (anonim ~400). Uzun izleme icin:
#   set OPENSKY_USER=kullaniciadi   (Windows: $env:OPENSKY_USER="...")
#   set OPENSKY_PASS=parola
_USER = os.environ.get("OPENSKY_USER")
_PASS = os.environ.get("OPENSKY_PASS")
_AUTH = (_USER, _PASS) if _USER and _PASS else None


def authenticated() -> bool:
    """OpenSky kimligi ayarli mi?"""
    return _AUTH is not None


@dataclass
class Aircraft:
    """Tek bir uçagin tek bir zamandaki durumu."""
    icao24: str
    callsign: str
    country: str
    lon: float | None
    lat: float | None
    baro_alt: float | None      # metre
    geo_alt: float | None       # metre
    on_ground: bool
    velocity: float | None      # m/s
    track: float | None
    vertical_rate: float | None # m/s
    squawk: str | None
    timestamp: float            # snapshot zamani (unix)
    position_source: int | None = None  # 0=ADS-B 1=ASTERIX 2=MLAT 3=FLARM

    @property
    def has_position(self) -> bool:
        return self.lat is not None and self.lon is not None


def _parse_state(state: list, snapshot_time: float) -> Aircraft:
    def g(i):
        return state[i] if i < len(state) else None

    callsign = (g(1) or "").strip()
    return Aircraft(
        icao24=(g(0) or "").strip(),
        callsign=callsign,
        country=g(2) or "",
        lon=g(5),
        lat=g(6),
        baro_alt=g(7),
        geo_alt=g(13),
        on_ground=bool(g(8)),
        velocity=g(9),
        track=g(10),
        vertical_rate=g(11),
        squawk=g(14),
        timestamp=snapshot_time,
        position_source=g(16),
    )


def fetch_states(bbox: tuple[float, float, float, float] | None = None,
                 timeout: int = 30, retries: int = 2) -> list[Aircraft]:
    """Canli durum anlik goruntusu (snapshot) getirir.

    bbox = (lamin, lomin, lamax, lomax) verilirse sadece o kutu.
    Ornek Turkiye civari: (35.0, 25.0, 43.0, 45.0)

    SAGLAMLIK: timeout uzun (30s — OpenSky/Cloud yavas olabilir), retry'li.
    Auth'lu istek timeout/hata verirse ANONIM dener (auth bazen yavaslatir).
    """
    params = {}
    if bbox:
        lamin, lomin, lamax, lomax = bbox
        params = {"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax}

    last_err = None
    # 1) Auth varsa auth'lu dene, sonra anonim; auth yoksa sadece anonim
    auth_options = [_AUTH, None] if _AUTH else [None]

    for attempt in range(retries + 1):
        for auth in auth_options:
            try:
                resp = requests.get(OPENSKY_URL, params=params,
                                    timeout=timeout, auth=auth)
                resp.raise_for_status()
                data = resp.json()
                snapshot_time = data.get("time", time.time())
                states = data.get("states") or []
                return [_parse_state(s, snapshot_time) for s in states]
            except Exception as e:
                last_err = e
                continue
        time.sleep(2)  # retry oncesi kisa bekle

    raise RuntimeError(f"OpenSky'a ulaşılamadı ({retries + 1} deneme): {last_err}")
