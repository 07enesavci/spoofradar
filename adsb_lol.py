"""adsb.lol — Cloud'dan erisilebilen ucretsiz canli ADS-B kaynagi.

OpenSky datacenter IP'lerini engelliyor/timeout veriyor (Streamlit Cloud'da
canli veri gelmez). adsb.lol (topluluk beslemesi) anahtar istemez ve bulut
sunuculardan erisilebilir — deploy sitede GERCEK ucaklar akar.

API (v2): https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{nm}
  Merkez nokta + yaricap (deniz mili). Yaricap ust siniri ~250 nm.
  Donen JSON: { "ac": [ { hex, flight, lat, lon, alt_baro, gs, track,
                          baro_rate, squawk, t, ... }, ... ] }

Alan birimleri OpenSky'dan FARKLI — burada Aircraft'a cevrilir:
  alt_baro/alt_geom: FEET  -> metre
  gs (ground speed): KNOT  -> m/s
  baro_rate:         ft/dk -> m/s
"""

from __future__ import annotations

import time

import requests

from opensky import Aircraft

ADSBLOL_URL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"

FT_TO_M = 0.3048
KNOT_TO_MS = 0.514444
FTMIN_TO_MS = 0.00508
MAX_DIST_NM = 250          # adsb.lol yaricap ust siniri


def _bbox_to_center_radius(bbox):
    """bbox (lamin,lomin,lamax,lomax) -> (merkez_lat, merkez_lon, yaricap_nm)."""
    if not bbox:
        return 39.0, 35.0, MAX_DIST_NM
    lamin, lomin, lamax, lomax = bbox
    clat = (lamin + lamax) / 2
    clon = (lomin + lomax) / 2
    # kabaca yari-kosegen (nm). 1 derece lat ~ 60 nm.
    half_lat_nm = abs(lamax - lamin) / 2 * 60
    half_lon_nm = abs(lomax - lomin) / 2 * 60
    radius = min(MAX_DIST_NM, max(half_lat_nm, half_lon_nm))
    return clat, clon, int(radius) or 100


def _num(v):
    """Sayi degilse ( or. alt_baro='ground') None don."""
    return v if isinstance(v, (int, float)) else None


def _parse(ac: dict, snapshot_time: float) -> Aircraft:
    alt_baro = _num(ac.get("alt_baro"))
    alt_geom = _num(ac.get("alt_geom"))
    gs = _num(ac.get("gs"))
    rate = _num(ac.get("baro_rate"))
    if rate is None:
        rate = _num(ac.get("geom_rate"))
    on_ground = ac.get("alt_baro") == "ground"
    return Aircraft(
        icao24=(ac.get("hex") or "").strip().lower(),
        callsign=(ac.get("flight") or "").strip(),
        country="",  # adsb.lol ulke vermez (cagri-ulke dogrulamasi 'bilinmiyor')
        lon=_num(ac.get("lon")),
        lat=_num(ac.get("lat")),
        baro_alt=alt_baro * FT_TO_M if alt_baro is not None else None,
        geo_alt=alt_geom * FT_TO_M if alt_geom is not None else None,
        on_ground=on_ground,
        velocity=gs * KNOT_TO_MS if gs is not None else None,
        track=_num(ac.get("track")),
        vertical_rate=rate * FTMIN_TO_MS if rate is not None else None,
        squawk=str(ac.get("squawk")) if ac.get("squawk") else None,
        timestamp=snapshot_time,
        position_source=0,  # ADS-B
    )


def fetch_states(bbox=None, timeout: tuple[int, int] = (6, 15)) -> list[Aircraft]:
    """adsb.lol'dan canli durum anlik goruntusu. Aircraft listesi doner.

    bbox merkez+yaricapa cevrilir (adsb.lol nokta-tabanli). Turkiye gibi genis
    bolgede tek ~250nm daire merkezi kapsar (yuzlerce ucak) — bbox'in tam
    ayni olmasa da gercek trafik. Hata/timeout'ta exception (cagiran fallback).
    """
    clat, clon, dist = _bbox_to_center_radius(bbox)
    url = ADSBLOL_URL.format(lat=clat, lon=clon, dist=dist)
    resp = requests.get(url, timeout=timeout,
                        headers={"User-Agent": "spoofradar/1.0 (defensive research)"})
    resp.raise_for_status()
    data = resp.json()
    now = data.get("now")
    snapshot_time = (now / 1000.0) if isinstance(now, (int, float)) else time.time()
    ac_list = data.get("ac") or []
    out = [_parse(a, snapshot_time) for a in ac_list]
    # gecerli konumlu olanlar (bazi kayitlar konumsuz olabilir)
    return [a for a in out if a.icao24]
