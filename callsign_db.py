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
    # --- genisletilmis havayolu tablosu ---
    "THY": ("Turkish Airlines", "Turkey"),
    "OHY": ("Onur Air", "Turkey"),
    "FHY": ("Freebird Airlines", "Turkey"),
    "TCW": ("Türkiye Air (kargo)", "Turkey"),
    "BBH": ("Ada Havayolları", "Turkey"),
    "KZR": ("Air Astana", "Kazakhstan"),
    "AZG": ("Silk Way West", "Azerbaijan"),
    "AHY": ("Azerbaijan Airlines", "Azerbaijan"),
    "GEA": ("Georgian Airways", "Georgia"),
    "BGA": ("Airzena", "Georgia"),
    "SYR": ("Syrian Air", "Syria"),
    "IRA": ("Iran Air", "Iran"),
    "IRM": ("Mahan Air", "Iran"),
    "ABY": ("Air Arabia", "United Arab Emirates"),
    "FDB": ("flydubai", "United Arab Emirates"),
    "RJA": ("Royal Jordanian", "Jordan"),
    "MEA": ("Middle East Airlines", "Lebanon"),
    "RBG": ("Rotana Jet", "United Arab Emirates"),
    "KAC": ("Kuwait Airways", "Kuwait"),
    "OMA": ("Oman Air", "Oman"),
    "GFA": ("Gulf Air", "Bahrain"),
    "IAW": ("Iraqi Airways", "Iraq"),
    "ETH": ("Ethiopian Airlines", "Ethiopia"),
    "MSC": ("Air Cairo", "Egypt"),
    "AMC": ("Air Malta", "Malta"),
    "TAR": ("Tunisair", "Tunisia"),
    "DAH": ("Air Algérie", "Algeria"),
    "RAM": ("Royal Air Maroc", "Morocco"),
    "SAA": ("South African Airways", "South Africa"),
    "KQA": ("Kenya Airways", "Kenya"),
    "VIR": ("Virgin Atlantic", "United Kingdom"),
    "EXS": ("Jet2", "United Kingdom"),
    "TOM": ("TUI Airways", "United Kingdom"),
    "TCX": ("Thomas Cook", "United Kingdom"),
    "EIN": ("Aer Lingus", "Ireland"),
    "NAX": ("Norwegian", "Norway"),
    "SAS": ("SAS", "Sweden"),
    "FIN": ("Finnair", "Finland"),
    "ICE": ("Icelandair", "Iceland"),
    "AEE": ("Aegean Airlines", "Greece"),
    "OAL": ("Olympic Air", "Greece"),
    "TAP": ("TAP Air Portugal", "Portugal"),
    "VLG": ("Vueling", "Spain"),
    "IBS": ("Iberia Express", "Spain"),
    "AEA": ("Air Europa", "Spain"),
    "EWG": ("Eurowings", "Germany"),
    "CFG": ("Condor", "Germany"),
    "BER": ("Air Berlin", "Germany"),
    "TUI": ("TUIfly", "Germany"),
    "BEL": ("Brussels Airlines", "Belgium"),
    "TVF": ("Transavia France", "France"),
    "TVS": ("Transavia", "Netherlands"),
    "HV": ("Transavia", "Netherlands"),
    "CTN": ("Croatia Airlines", "Croatia"),
    "ROT": ("TAROM", "Romania"),
    "LOT": ("LOT Polish Airlines", "Poland"),
    "CSA": ("Czech Airlines", "Czechia"),
    "AUA": ("Austrian", "Austria"),
    "SWR": ("Swiss", "Switzerland"),
    "BCS": ("European Air Transport", "Belgium"),
    "AFL": ("Aeroflot", "Russian Federation"),
    "SVR": ("Ural Airlines", "Russian Federation"),
    "SBI": ("S7 Airlines", "Russian Federation"),
    "PBD": ("Pobeda", "Russian Federation"),
    "UZB": ("Uzbekistan Airways", "Uzbekistan"),
    "TJK": ("Somon Air", "Tajikistan"),
    "JZR": ("Jazeera Airways", "Kuwait"),
    "QTR": ("Qatar Airways", "Qatar"),
    "ETD": ("Etihad", "United Arab Emirates"),
    "UAE": ("Emirates", "United Arab Emirates"),
    "SIA": ("Singapore Airlines", "Singapore"),
    "MAS": ("Malaysia Airlines", "Malaysia"),
    "AXM": ("AirAsia", "Malaysia"),
    "GIA": ("Garuda Indonesia", "Indonesia"),
    "CPA": ("Cathay Pacific", "Hong Kong"),
    "HDA": ("Hong Kong Dragon", "Hong Kong"),
    "EVA": ("EVA Air", "Taiwan"),
    "CAL": ("China Airlines", "Taiwan"),
    "KAL": ("Korean Air", "South Korea"),
    "AAR": ("Asiana", "South Korea"),
    "PAL": ("Philippine Airlines", "Philippines"),
    "AIC": ("Air India", "India"),
    "IGO": ("IndiGo", "India"),
    "VTI": ("Vistara", "India"),
    "PIA": ("Pakistan Intl", "Pakistan"),
    "ACA": ("Air Canada", "Canada"),
    "WJA": ("WestJet", "Canada"),
    "JBU": ("JetBlue", "United States"),
    "FFT": ("Frontier", "United States"),
    "NKS": ("Spirit", "United States"),
    "ASA": ("Alaska Airlines", "United States"),
    "AMX": ("Aeroméxico", "Mexico"),
    "VOI": ("Volaris", "Mexico"),
    "TAM": ("LATAM Brasil", "Brazil"),
    "GLO": ("GOL", "Brazil"),
    "AZU": ("Azul", "Brazil"),
    "ARG": ("Aerolíneas Argentinas", "Argentina"),
    "ANZ": ("Air New Zealand", "New Zealand"),
    "JST": ("Jetstar", "Australia"),
    "VOZ": ("Virgin Australia", "Australia"),
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
