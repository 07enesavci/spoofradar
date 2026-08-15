"""Callsign (cagri isareti) dogrulama.

Cagri isareti ilk 3 harfi = havayolu ICAO kodu (ornek THY=Turkish, PGT=Pegasus).
Bu kodun ait oldugu ulke ile uçagin bildirdigi 'origin_country' uyuyor mu?
Uyusmazlik = süpheli (spoofer rastgele callsign uydurmus olabilir).

Not: kapsamli havayolu veritabani buyuk; burada en yaygin havayolu ICAO
kodlari var. Bilinmeyen kod = dogrulanamaz (süpheli degil).
"""

from __future__ import annotations

# En yaygin havayolu ICAO kodu -> (isim, ana ulke)
AIRLINE_CODES = {
    "THY": ("Turkish Airlines", "Turkey"),
    "PGT": ("Pegasus", "Turkey"),
    "SXS": ("SunExpress", "Turkey"),
    "TKJ": ("AJet", "Turkey"),
    "KKK": ("AtlasGlobal", "Turkey"),
    "DLH": ("Lufthansa", "Germany"),
    "BAW": ("British Airways", "United Kingdom"),
    "AFR": ("Air France", "France"),
    "KLM": ("KLM", "Netherlands"),
    "UAE": ("Emirates", "United Arab Emirates"),
    "QTR": ("Qatar Airways", "Qatar"),
    "RYR": ("Ryanair", "Ireland"),
    "EZY": ("easyJet", "United Kingdom"),
    "AAL": ("American Airlines", "United States"),
    "UAL": ("United Airlines", "United States"),
    "DAL": ("Delta", "United States"),
    "SWA": ("Southwest", "United States"),
    "SVA": ("Saudia", "Saudi Arabia"),
    "MSR": ("EgyptAir", "Egypt"),
    "ELY": ("El Al", "Israel"),
    "AZA": ("ITA Airways", "Italy"),
    "IBE": ("Iberia", "Spain"),
    "SWR": ("Swiss", "Switzerland"),
    "AUA": ("Austrian", "Austria"),
    "THA": ("Thai Airways", "Thailand"),
    "SIA": ("Singapore Airlines", "Singapore"),
    "UAA": ("United", "United States"),
    "WZZ": ("Wizz Air", "Hungary"),
    "AFL": ("Aeroflot", "Russian Federation"),
    "GFA": ("Gulf Air", "Bahrain"),
    "ETD": ("Etihad", "United Arab Emirates"),
    "QFA": ("Qantas", "Australia"),
    "ANA": ("All Nippon", "Japan"),
    "JAL": ("Japan Airlines", "Japan"),
    "CCA": ("Air China", "China"),
    "CES": ("China Eastern", "China"),
    "CSN": ("China Southern", "China"),
}


def validate_callsign(callsign: str, origin_country: str) -> dict:
    """Cagri isareti havayolu kodu ile ulke uyuyor mu?

    Doner: {status, airline, detail}
      status: 'ok' | 'mismatch' | 'unknown' | 'empty'
    """
    cs = (callsign or "").strip().upper()
    if not cs or len(cs) < 3:
        return {"status": "empty", "airline": None, "detail": "Çağrı işareti yok/kısa."}

    code = cs[:3]
    if not code.isalpha():
        return {"status": "unknown", "airline": None,
                "detail": "Havayolu kodu değil (özel/askeri olabilir)."}

    entry = AIRLINE_CODES.get(code)
    if entry is None:
        return {"status": "unknown", "airline": None,
                "detail": f"'{code}' bilinmeyen havayolu kodu — doğrulanamaz."}

    name, country = entry
    # Ulke bilgisi YOKSA (or. adsb.lol origin_country vermez) uyusmazlik
    # SAYMA — dogrulanamaz. Yoksa her taninan havayolu yanlis-pozitif olur.
    if not (origin_country or "").strip():
        return {"status": "unknown", "airline": name,
                "detail": f"{name} — kaynak ülke bilgisi vermiyor, doğrulanamaz."}
    if country.lower() == origin_country.lower():
        return {"status": "ok", "airline": name,
                "detail": f"{name} ({country}) — ülke uyumlu."}
    return {"status": "mismatch", "airline": name,
            "detail": f"'{code}'={name} normalde {country}, ama uçak "
                      f"{origin_country} bildiriyor — uyuşmazlık, şüpheli."}
