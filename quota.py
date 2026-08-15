"""OpenSky kota (kredi) koruma.

OpenSky her /states/all istegini bbox alanina gore KREDI ile ucretlendirir:
  alan (derece^2) <=25 → 1, <=100 → 2, <=400 → 3, ustu/global → 4
Gunluk kota: anonim ~400, kayitli ~4000 kredi. Kota UTC gece yarisi sifirlanir.

Bu modul:
  - Her istegin maliyetini hesaplar
  - Gunluk kullanilan krediyi diske kalici tutar (surec yeniden basladiginda korunur)
  - Kota azaldikca cekme araligini otomatik uzatir (reset'e kadar dayansin)
  - Kredi kalmayinca reset'e kadar duraklatir
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone, timedelta

STATE_FILE = os.path.join(os.path.dirname(__file__), "quota_state.json")

ANON_BUDGET = 400
AUTH_BUDGET = 4000


def credit_cost(bbox: tuple[float, float, float, float] | None) -> int:
    """bbox'in kredi maliyeti. None = global = 4."""
    if bbox is None:
        return 4
    lamin, lomin, lamax, lomax = bbox
    area = abs(lamax - lamin) * abs(lomax - lomin)  # derece^2
    if area <= 25:
        return 1
    if area <= 100:
        return 2
    if area <= 400:
        return 3
    return 4


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _seconds_to_reset() -> float:
    """UTC gece yarisina kalan saniye."""
    now = datetime.now(timezone.utc)
    nxt = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (nxt - now).total_seconds()


class QuotaTracker:
    def __init__(self, authenticated: bool = False):
        self.budget = AUTH_BUDGET if authenticated else ANON_BUDGET
        self.date = _today_utc()
        self.used = 0
        self._load()

    # --- kalicilik ---------------------------------------------------------
    def _load(self) -> None:
        try:
            with open(STATE_FILE) as f:
                data = json.load(f)
            if data.get("date") == self.date:
                self.used = int(data.get("used", 0))
            else:
                self.used = 0  # yeni gun = sifirla
        except (FileNotFoundError, ValueError, KeyError):
            self.used = 0

    def _save(self) -> None:
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({"date": self.date, "used": self.used}, f)
        except OSError:
            pass  # kalicilik basarisiz olsa da calismaya devam et

    def _rollover(self) -> None:
        """Gun degistiyse sayaci sifirla."""
        today = _today_utc()
        if today != self.date:
            self.date = today
            self.used = 0
            self._save()

    # --- API ---------------------------------------------------------------
    def record(self, cost: int) -> None:
        """Bir istegin maliyetini isle."""
        self._rollover()
        self.used += cost
        self._save()

    @property
    def remaining(self) -> int:
        self._rollover()
        return max(0, self.budget - self.used)

    def can_afford(self, cost: int) -> bool:
        return self.remaining >= cost

    def next_interval(self, base: int, cost: int, low_frac: float = 0.15) -> float:
        """Onerilen bir sonraki cekme araligi (saniye).

        Kota bol → base araligi kullan.
        Kota %low_frac altina indi → kalan krediyi reset'e kadar YAY.
        Kredi bitti → reset'e kadar duraklat.
        """
        rem = self.remaining
        if rem < cost:
            return _seconds_to_reset()  # duraklat, sifirlanmayi bekle

        low_threshold = max(cost * 10, self.budget * low_frac)
        if rem > low_threshold:
            return float(base)

        # yayilim modu: kalan cagriyi kalan sureye dagit
        calls_left = rem / cost
        spread = _seconds_to_reset() / calls_left if calls_left else _seconds_to_reset()
        return max(float(base), math.ceil(spread))

    def status(self, cost: int) -> dict:
        """Panele gostermek icin ozet."""
        rem = self.remaining
        return {
            "used": self.used,
            "budget": self.budget,
            "remaining": rem,
            "cost_per_call": cost,
            "calls_left": rem // cost if cost else 0,
            "low": rem <= max(cost * 10, self.budget * 0.15),
            "exhausted": rem < cost,
            "reset_in_min": round(_seconds_to_reset() / 60),
        }
