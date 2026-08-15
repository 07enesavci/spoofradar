"""Uçak parmak izi: her uçagin kendi 'normal'inden sapmasi.

Genel ML (ml_detector) tum filoya bakar. Fingerprint ise TEK uçagin kendi
gecmisine bakar: bir uçak surekli 250 m/s seyir ederken aniden 400 m/s
gosterirse, filo icinde normal olsa bile O uçak icin anormaldir.

Oturum boyunca uçak basina kayan istatistik (ortalama/std) tutulur.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from opensky import Aircraft


@dataclass
class Profile:
    vals_vel: deque = field(default_factory=lambda: deque(maxlen=30))
    vals_alt: deque = field(default_factory=lambda: deque(maxlen=30))


class FingerprintStore:
    def __init__(self, min_obs: int = 8):
        self.profiles: dict[str, Profile] = defaultdict(Profile)
        self.min_obs = min_obs

    def observe(self, aircraft: list[Aircraft]) -> None:
        for ac in aircraft:
            if not ac.icao24:
                continue
            p = self.profiles[ac.icao24]
            if ac.velocity is not None:
                p.vals_vel.append(ac.velocity)
            if ac.baro_alt is not None:
                p.vals_alt.append(ac.baro_alt)

    @staticmethod
    def _z(series, x, min_std: float) -> float:
        """Robust z-score. min_std = taban std (sifira bolme + minik-fark
        dev-z yanlis-pozitifini onler). Alan-basina verilir."""
        n = len(series)
        if n < 2:
            return 0.0
        mean = sum(series) / n
        var = sum((v - mean) ** 2 for v in series) / n
        std = max(var ** 0.5, min_std)
        return abs(x - mean) / std

    # Alan-basina taban std: hiz ~5 m/s, irtifa ~50 m (dogal dalgalanma)
    MIN_STD_VEL = 5.0
    MIN_STD_ALT = 50.0

    def deviations(self, aircraft: list[Aircraft], z_thresh: float = 4.0):
        """Kendi profilinden sapan uçaklar (icao24, alan, z)."""
        out = []
        for ac in aircraft:
            p = self.profiles.get(ac.icao24)
            if not p or len(p.vals_vel) < self.min_obs:
                continue
            if ac.velocity is not None:
                zv = self._z(list(p.vals_vel)[:-1] or p.vals_vel, ac.velocity,
                             self.MIN_STD_VEL)
                if zv > z_thresh:
                    out.append((ac.icao24, ac.callsign or "-", "hız", round(zv, 1)))
            if ac.baro_alt is not None and len(p.vals_alt) >= self.min_obs:
                za = self._z(list(p.vals_alt)[:-1] or p.vals_alt, ac.baro_alt,
                             self.MIN_STD_ALT)
                if za > z_thresh:
                    out.append((ac.icao24, ac.callsign or "-", "irtifa", round(za, 1)))
        return out
