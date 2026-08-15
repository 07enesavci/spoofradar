"""Uçak zenginlestirme: askeri tespit, guven skoru, sinyal kaynagi.

Bu modul ham durum verisini yorumlar:
  - is_military: ICAO24 hex adres araligina gore askeri uçak tahmini
  - trust_score: 0-100 "gerçeklik/güven" skoru (alarm + sinyal kalitesine gore)
  - source_label: konum kaynagini insan-okur yap (ADS-B / MLAT ...)
"""

from __future__ import annotations

from opensky import Aircraft

# Askeri ICAO24 hex on-ekleri. DAR ve iyi-bilinen bloklar (yanlis pozitif
# olmasin diye sivil bloklara girmeyenler). Yaklasik gostergedir, kesin degil.
MILITARY_PREFIXES = (
    "ae",     # ABD askeri (AE????)
    "adf",    # ABD askeri (ADF???)
    "43c",    # Birlesik Krallik askeri (43C???)
)

SOURCE_LABELS = {
    0: "ADS-B",
    1: "ASTERIX",
    2: "MLAT (çoklu-alıcı)",
    3: "FLARM",
}


def is_military(icao24: str) -> bool:
    """ICAO24 hex askeri araliga mi giriyor? (yaklasik tahmin)"""
    h = (icao24 or "").lower()
    return h.startswith(MILITARY_PREFIXES)


def source_label(ac: Aircraft) -> str:
    """Konum kaynagi etiketi."""
    return SOURCE_LABELS.get(ac.position_source, "bilinmiyor")


def trust_score(ac: Aircraft, high: bool, warn: bool,
                ml: bool, emergency: bool = False) -> int:
    """0-100 güven skoru. Yuksek = veri daha güvenilir/tutarli.

    Fiziksel imkansizlik en cok dusurur; MLAT (bagimsiz dogrulama) yukseltir.
    Acil durum kodu skoru dusurmez (mesru olabilir) ama ayri isaretlenir.
    """
    s = 100
    if high:
        s -= 70          # fiziksel imkansizlik = güçlü spoof isareti
    if warn:
        s -= 20
    if ml:
        s -= 20          # ogrenilmis normalden sapma

    # Sinyal kalitesi
    if ac.geo_alt is None and ac.baro_alt is not None:
        s -= 10          # GNSS irtifasi yok = zayif sinyal / jamming süphesi
    if ac.position_source == 2:
        s += 10          # MLAT: konum bagimsiz uçgenlendi = spoof zor

    return max(0, min(100, s))


def trust_label(score: int) -> str:
    """Skoru kisa etikete cevir."""
    if score >= 80:
        return "🟢 güvenilir"
    if score >= 50:
        return "🟡 şüpheli"
    return "🔴 yüksek risk"
