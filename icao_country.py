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
_RANGES: list[tuple[int, int, str]] = [
    (0x010000, 0x017FFF, "Egypt"),
    (0x140000, 0x1FFFFF, "Russian Federation"),
    (0x300000, 0x33FFFF, "Italy"),
    (0x340000, 0x37FFFF, "Spain"),
    (0x380000, 0x3BFFFF, "France"),
    (0x3C0000, 0x3FFFFF, "Germany"),
    (0x400000, 0x43FFFF, "United Kingdom"),
    (0x440000, 0x447FFF, "Austria"),
    (0x448000, 0x44FFFF, "Belgium"),
    (0x458000, 0x45FFFF, "Denmark"),
    (0x460000, 0x467FFF, "Finland"),
    (0x468000, 0x46FFFF, "Greece"),
    (0x470000, 0x477FFF, "Hungary"),
    (0x478000, 0x47FFFF, "Norway"),
    (0x480000, 0x487FFF, "Netherlands"),
    (0x488000, 0x48FFFF, "Poland"),
    (0x490000, 0x497FFF, "Portugal"),
    (0x4A0000, 0x4A7FFF, "Sweden"),
    (0x4A8000, 0x4AFFFF, "Switzerland"),
    (0x4B0000, 0x4B7FFF, "Switzerland"),  # Isvicre ikinci blok
    (0x4B8000, 0x4BFFFF, "Turkey"),
    (0x4CA000, 0x4CAFFF, "Ireland"),
    (0x738000, 0x73FFFF, "Israel"),
    (0x710000, 0x717FFF, "Saudi Arabia"),
    (0x760000, 0x767FFF, "Singapore"),
    (0x768000, 0x76FFFF, "Singapore"),
    (0x780000, 0x7BFFFF, "China"),
    (0x7C0000, 0x7FFFFF, "Australia"),
    (0x840000, 0x87FFFF, "Japan"),
    (0x880000, 0x887FFF, "Thailand"),
    (0x894000, 0x894FFF, "Bahrain"),
    (0x896000, 0x896FFF, "United Arab Emirates"),
    (0x06A000, 0x06AFFF, "Qatar"),
    (0xA00000, 0xAFFFFF, "United States"),
    (0xC00000, 0xC3FFFF, "Canada"),
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
