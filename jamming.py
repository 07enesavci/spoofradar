"""GPS jamming / spoofing bolge tespiti (isi haritasi).

Dogrudan GPS dogruluk alani (NACp/NIC) temel OpenSky API'sinde yok. Ama:
  - baro_alt : barometrik irtifa (hava basincindan, GPS'ten BAGIMSIZ)
  - geo_alt  : geometrik irtifa (GNSS/GPS'ten)

GPS bozulunca (jamming/spoofing) geo_alt kaybolur veya baro'dan buyuk sapar.
Bunu her uçak icin "GNSS bozulmus mu?" bayragina cevirir, cografi izgaraya
(grid) toplar ve bozulma oraninin yuksek oldugu hucreleri jamming süphesi
olarak isaretler.

Not: Bu bir VEKIL (proxy) gostergedir; kesin kanit degil. Gercek jamming
tespiti icin NACp/NIC gerekir. Yine de bilinen jamming bolgeleriyle
(Baltik, Karadeniz, Ortadogu) korelasyon gosterir.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from opensky import Aircraft

# NOT: baro-geo farki NORMALDE ~500m (atmosferik basinc sapmasi, QNH).
# Canli veri olcumu: medyan 533m, p99 ~884m. Yani gercek anomali esigi
# normal populasyonun cok ustunde olmali. 1200m = p99+ (uçaklarin ~%0.7'si).
GNSS_DIVERGENCE_M = 1200.0
MIN_CRUISE_ALT = 3000.0   # yerdeki/alcak uçaklarda gurultu cok, filtrele


@dataclass
class GridCell:
    lat: float          # hucre merkez enlem
    lon: float          # hucre merkez boylam
    total: int          # hucredeki uçak sayisi
    degraded: int       # GNSS bozulmus uçak sayisi
    ratio: float        # bozulma orani 0..1


def gnss_degraded(ac: Aircraft) -> bool | None:
    """GNSS bozulma bayragi. Degerlendirilemezse None."""
    if ac.on_ground or ac.baro_alt is None or ac.baro_alt < MIN_CRUISE_ALT:
        return None
    if ac.geo_alt is None:
        return True  # GNSS irtifasi hic yok = güçlü bozulma isareti
    return abs(ac.geo_alt - ac.baro_alt) > GNSS_DIVERGENCE_M


def build_grid(aircraft: list[Aircraft], cell_deg: float = 1.0) -> list[GridCell]:
    """Uçaklari cografi izgaraya topla, hucre basina bozulma orani hesapla."""
    buckets: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    for ac in aircraft:
        if not ac.has_position:
            continue
        d = gnss_degraded(ac)
        if d is None:
            continue
        key = (int(ac.lat // cell_deg), int(ac.lon // cell_deg))
        buckets[key][0] += 1            # total
        if d:
            buckets[key][1] += 1        # degraded

    cells = []
    for (glat, glon), (total, degraded) in buckets.items():
        cells.append(GridCell(
            lat=(glat + 0.5) * cell_deg,
            lon=(glon + 0.5) * cell_deg,
            total=total,
            degraded=degraded,
            ratio=degraded / total if total else 0.0,
        ))
    return cells


def suspected_zones(cells: list[GridCell], min_total: int = 4,
                    min_ratio: float = 0.5) -> list[GridCell]:
    """Yeterli uçak + yuksek bozulma orani olan hucreler = jamming süphesi."""
    zones = [c for c in cells if c.total >= min_total and c.ratio >= min_ratio]
    return sorted(zones, key=lambda c: (c.ratio, c.total), reverse=True)
