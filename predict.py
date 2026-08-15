"""Rota tahmini + uçak tipi.

1. predict_position: mevcut hiz/yon/konumdan gelecek konumu tahmin et
   (dogrusal ekstrapolasyon). Rota izi ile karsilastirilirsa sapma anlasilir.
2. trajectory_deviation: uçak son izinden beklenen yonde mi gidiyor, yoksa
   ani sapiyor mu (spoof izi zigzag olur).
3. aircraft_type: ICAO24 hex'ten uçak tipi/tescil (hexdb.io ucretsiz API,
   anahtar gerektirmez; agdan cekemezse None).
"""

from __future__ import annotations

import math

import requests

from detectors import haversine


def predict_position(lat, lon, velocity_ms, track_deg, seconds: float = 60):
    """Mevcut konum + hiz + yondan gelecek konumu tahmin et (dogrusal)."""
    if velocity_ms is None or track_deg is None:
        return None
    dist = velocity_ms * seconds        # metre
    th = math.radians(track_deg)
    dn = dist * math.cos(th)            # kuzey bileseni
    de = dist * math.sin(th)            # dogu bileseni
    coslat = max(0.1, math.cos(math.radians(lat)))
    return (lat + dn / 111320.0, lon + de / (111320.0 * coslat))


def trajectory_deviation(track_points: list, velocity_ms, track_deg) -> dict | None:
    """Uçak son izinden beklenen yonde mi? track_points=[[lon,lat],...].

    Son iki noktadan gercek gidis yonu ile bildirilen track'i karsilastir.
    Buyuk fark = ani sapma (spoof/manevra). En az 3 nokta gerekir.
    """
    if len(track_points) < 3 or track_deg is None:
        return None
    # Son iki noktadan gercek bearing
    (lon1, lat1), (lon2, lat2) = track_points[-2], track_points[-1]
    d = haversine(lat1, lon1, lat2, lon2)
    if d < 100:  # cok az hareket, guvenilmez
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    actual_bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    diff = abs((actual_bearing - track_deg) % 360)
    diff = min(diff, 360 - diff)
    return {
        "actual_bearing": round(actual_bearing),
        "reported_track": round(track_deg),
        "deviation_deg": round(diff),
        "suspicious": diff > 45,
        "detail": (f"Rota sapması {diff:.0f}° (gerçek gidiş {actual_bearing:.0f}°, "
                   f"bildirilen {track_deg:.0f}°)."
                   if diff > 45 else f"Rota tutarlı ({diff:.0f}° sapma).")
    }


# --- Uçak tipi (hexdb.io ucretsiz, anahtarsiz) -----------------------------
_TYPE_CACHE: dict[str, dict] = {}


def aircraft_type(icao24: str, timeout: int = 4) -> dict | None:
    """ICAO24 hex -> uçak tipi/tescil/operator (hexdb.io). Onbellekli.

    Agdan cekemezse None doner (araç yine calisir).
    """
    h = (icao24 or "").lower().strip()
    if not h:
        return None
    if h in _TYPE_CACHE:
        return _TYPE_CACHE[h]
    try:
        r = requests.get(f"https://hexdb.io/api/v1/aircraft/{h}", timeout=timeout)
        if r.ok:
            data = r.json()
            info = {
                "registration": data.get("Registration"),
                "type": data.get("Type") or data.get("ICAOTypeCode"),
                "operator": data.get("RegisteredOwners"),
                "manufacturer": data.get("Manufacturer"),
            }
            _TYPE_CACHE[h] = info
            return info
    except Exception:
        pass
    _TYPE_CACHE[h] = None
    return None


# --- Uçak fotografi (planespotters.net ucretsiz, anahtarsiz) ---------------
_PHOTO_CACHE: dict[str, dict] = {}


def aircraft_photo(icao24: str, registration: str | None = None,
                   timeout: int = 5) -> dict | None:
    """ICAO24 (veya tescil) -> gercek ucak fotografi (planespotters.net).

    Doner: {thumb, link, photographer} veya None. Onbellekli, anahtarsiz.
    Atif ZORUNLU (planespotters kurali): fotografci adi + link gosterilir.
    """
    h = (icao24 or "").lower().strip()
    if not h:
        return None
    if h in _PHOTO_CACHE:
        return _PHOTO_CACHE[h]

    urls = [f"https://api.planespotters.net/pub/photos/hex/{h}"]
    if registration:
        urls.append(f"https://api.planespotters.net/pub/photos/reg/"
                    f"{registration.strip()}")
    # planespotters KURALI: User-Agent'ta iletisim URL'i/e-posta ZORUNLU
    # (yoksa 403). Bu olmadan API foto vermez.
    ua = "spoofradar/1.0 (+https://github.com/07enesavci/spoofradar)"
    info = None
    for url in urls:
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": ua})
            if not r.ok:
                continue
            photos = (r.json() or {}).get("photos") or []
            if not photos:
                continue
            p = photos[0]
            thumb = (p.get("thumbnail_large") or p.get("thumbnail") or {})
            src = thumb.get("src")
            if src:
                info = {
                    "thumb": src,
                    "link": p.get("link"),
                    "photographer": p.get("photographer"),
                }
                break
        except Exception:
            continue
    _PHOTO_CACHE[h] = info
    return info
