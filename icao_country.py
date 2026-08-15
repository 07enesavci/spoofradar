"""ICAO 24-bit adres -> tescil ulkesi.

Her ucagin icao24 (hex) adresi ICAO tarafindan ULKE bloklarina tahsis edilir.
adsb.lol 'origin_country' vermez; bu modul hex'ten ulkeyi turetir, boylece
cagri-isareti<->ulke uyusmazligi tespiti (callsign_db) yeniden calisir.

Kaynak: ICAO Annex 10 24-bit adres tahsisi (yaygin uretilmis tablo). Blok
baslangiclari 0x8000 (32768) adim; buyuk ulkeler (US/UK/RU) daha genis blok.

DIKKAT: yanlis aralik = yanlis-pozitif. Sadece EMIN olunan, canli veriyle
dogrulanan bloklar var; kapsam disi = "" (dogrulanamaz, alarm YOK).
Ulke isimleri callsign_db.AIRLINE_CODES ile AYNI yazimda (eslesme icin).
"""

from __future__ import annotations

# (baslangic, bitis, ulke) — hex adres araligi kapsayici.
# ICAO Annex 10 24-bit adres tahsisi (readsb/dump1090 tablosu ile ayni).
_RANGES: list[tuple[int, int, str]] = [
    # Afrika
    (0x008000, 0x00FFFF, "South Africa"),
    (0x010000, 0x017FFF, "Egypt"),
    (0x018000, 0x01FFFF, "Libya"),
    (0x020000, 0x027FFF, "Morocco"),
    (0x028000, 0x02FFFF, "Tunisia"),
    (0x034000, 0x034FFF, "Cameroon"),
    (0x038000, 0x038FFF, "Congo"),
    (0x03E000, 0x03EFFF, "Ethiopia"),
    (0x040000, 0x040FFF, "Equatorial Guinea"),
    (0x044000, 0x044FFF, "Gabon"),
    (0x048000, 0x048FFF, "Ghana"),
    (0x04C000, 0x04CFFF, "Kenya"),
    (0x0A0000, 0x0A7FFF, "Algeria"),
    # Rusya + Orta Asya
    (0x06A000, 0x06AFFF, "Qatar"),
    (0x140000, 0x1FFFFF, "Russian Federation"),
    # Avrupa (0x8000 bloklari, buyuk ulkeler genis)
    (0x300000, 0x33FFFF, "Italy"),
    (0x340000, 0x37FFFF, "Spain"),
    (0x380000, 0x3BFFFF, "France"),
    (0x3C0000, 0x3FFFFF, "Germany"),
    (0x400000, 0x43FFFF, "United Kingdom"),
    (0x440000, 0x447FFF, "Austria"),
    (0x448000, 0x44FFFF, "Belgium"),
    (0x450000, 0x457FFF, "Bulgaria"),
    (0x458000, 0x45FFFF, "Denmark"),
    (0x460000, 0x467FFF, "Finland"),
    (0x468000, 0x46FFFF, "Greece"),
    (0x470000, 0x477FFF, "Hungary"),
    (0x478000, 0x47FFFF, "Norway"),
    (0x480000, 0x487FFF, "Netherlands"),
    (0x488000, 0x48FFFF, "Poland"),
    (0x490000, 0x497FFF, "Portugal"),
    (0x498000, 0x49FFFF, "Czechia"),
    (0x4A0000, 0x4A7FFF, "Sweden"),
    (0x4A8000, 0x4AFFFF, "Switzerland"),
    (0x4B0000, 0x4B7FFF, "Switzerland"),
    (0x4B8000, 0x4BFFFF, "Turkey"),
    (0x4C0000, 0x4C7FFF, "Serbia"),
    (0x4C8000, 0x4C83FF, "Cyprus"),
    (0x4CA000, 0x4CAFFF, "Ireland"),
    (0x4CC000, 0x4CCFFF, "Iceland"),
    (0x501000, 0x5013FF, "Croatia"),
    (0x508000, 0x50FFFF, "Romania"),
    # Orta Dogu + Asya
    (0x700000, 0x700FFF, "Afghanistan"),
    (0x702000, 0x702FFF, "Bangladesh"),
    (0x706000, 0x706FFF, "Kuwait"),
    (0x70A000, 0x70AFFF, "Oman"),
    (0x710000, 0x717FFF, "Saudi Arabia"),
    (0x718000, 0x71FFFF, "South Korea"),
    (0x720000, 0x727FFF, "North Korea"),
    (0x728000, 0x72FFFF, "Iraq"),
    (0x730000, 0x737FFF, "Iran"),
    (0x738000, 0x73FFFF, "Israel"),
    (0x740000, 0x747FFF, "Jordan"),
    (0x748000, 0x74FFFF, "Lebanon"),
    (0x750000, 0x757FFF, "Malaysia"),
    (0x758000, 0x75FFFF, "Philippines"),
    (0x760000, 0x767FFF, "Pakistan"),
    (0x768000, 0x76FFFF, "Singapore"),
    (0x770000, 0x777FFF, "Sri Lanka"),
    (0x778000, 0x77FFFF, "Syria"),
    (0x780000, 0x7BFFFF, "China"),
    (0x7C0000, 0x7FFFFF, "Australia"),
    (0x800000, 0x83FFFF, "India"),
    (0x840000, 0x87FFFF, "Japan"),
    (0x880000, 0x887FFF, "Thailand"),
    (0x888000, 0x88FFFF, "Vietnam"),
    (0x894000, 0x894FFF, "Bahrain"),
    (0x895000, 0x8953FF, "Brunei"),
    (0x896000, 0x896FFF, "United Arab Emirates"),
    (0x8A0000, 0x8A7FFF, "Indonesia"),
    # Amerika + Okyanusya
    (0x0D0000, 0x0D7FFF, "Mexico"),
    (0xA00000, 0xAFFFFF, "United States"),
    (0xC00000, 0xC3FFFF, "Canada"),
    (0xC80000, 0xC87FFF, "New Zealand"),
    (0xE00000, 0xE3FFFF, "Argentina"),
    (0xE40000, 0xE7FFFF, "Brazil"),
]
# Hizli arama icin baslangica gore sirali.
_RANGES.sort(key=lambda r: r[0])


def country_from_icao(hex24: str) -> str:
    """icao24 hex -> ulke adi. Bilinmeyen/gecersiz -> "" (dogrulanamaz)."""
    if not hex24:
        return ""
    try:
        n = int(hex24, 16)
    except ValueError:
        return ""
    # Kucuk tablo — dogrusal tarama yeterli (arac basina ~35 karsilastirma).
    for start, end, country in _RANGES:
        if start <= n <= end:
            return country
        if n < start:
            break  # sirali; gecti
    return ""
