"""ML tabanli anomali tespiti (denetimsiz / unsupervised).

Kural-tabanli tespit sadece bildigimiz fiziksel ihlalleri yakalar.
ML katmani ise "normal trafik neye benzer" ogrenir ve **ogrenilmemis**
sapmalari (aykiri deger / outlier) isaretler. Etiketli veri gerekmez.

Yaklasim: son N snapshot'tan uçak ozellik vektorleri toplanir, uzerine
IsolationForest egitilir, sonra her yeni uçak skorlanir. Skor negatifse
model onu aykiri (süpheli) sayar.

scikit-learn yoksa saf-Python istatistiksel yedek (robust z-score / MAD)
devreye girer, boylece araç her kosulda calisir.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from opensky import Aircraft

# sklearn opsiyonel — yoksa yedek yontem kullanilir
try:
    import numpy as np
    from sklearn.ensemble import IsolationForest
    _HAS_SKLEARN = True
except Exception:  # ImportError veya derleme sorunu
    _HAS_SKLEARN = False


@dataclass
class MLAlert:
    icao24: str
    callsign: str
    score: float       # dusuk = daha aykiri
    detail: str


def features(ac: Aircraft) -> list[float] | None:
    """Uçaktan sayisal ozellik vektoru cikar. Eksik veri varsa None."""
    if ac.velocity is None or ac.baro_alt is None:
        return None
    vr = ac.vertical_rate if ac.vertical_rate is not None else 0.0
    track = ac.track if ac.track is not None else 0.0
    geo = ac.geo_alt if ac.geo_alt is not None else ac.baro_alt
    alt_diff = geo - ac.baro_alt   # baro vs geometrik irtifa farki
    return [ac.velocity, vr, ac.baro_alt, alt_diff, track]


class AnomalyModel:
    """Kayan pencere uzerinde egitilen denetimsiz aykiri deger tespiti."""

    def __init__(self, window: int = 2000, min_train: int = 300,
                 contamination: float = 0.02, score_threshold: float = -0.60):
        self.buffer: deque[list[float]] = deque(maxlen=window)
        self.min_train = min_train
        self.contamination = contamination
        # MUTLAK esik: IsolationForest'in sabit-yuzde (contamination) predict()
        # yerine ham skora bakariz. Temiz trafik = cok az flag; sadece gercekten
        # uç uçaklar isaretlenir. 4269 canli ornekle egitilmis model.pkl uzerinde
        # kalibre: skor medyani ~-0.44, min ~-0.63; -0.60 = ~%0.23 (nadir, anlamli
        # 'incele' listesi — yanlis-pozitif cok dusuk).
        self.score_threshold = score_threshold
        self.model = None
        self._backend = "sklearn" if _HAS_SKLEARN else "mad"

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def trained(self) -> bool:
        return self.model is not None if _HAS_SKLEARN else len(self.buffer) >= self.min_train

    def observe(self, aircraft: list[Aircraft]) -> None:
        """Gozlemleri egitim tamponuna ekle."""
        for ac in aircraft:
            f = features(ac)
            if f is not None:
                self.buffer.append(f)

    def load_pretrained(self) -> bool:
        """Diskteki kalici modeli (history_train.py ciktisi) yukle.

        Varsa ISINMA BEKLEMEDEN olgun tespit yapar. Doner: yuklendi mi.
        """
        if not _HAS_SKLEARN:
            return False
        try:
            from history_train import load_model
            m = load_model()
            if m is not None:
                self.model = m
                return True
        except Exception:
            pass
        return False

    def fit(self) -> None:
        """Tampon yeterliyse modeli (yeniden) egit."""
        if len(self.buffer) < self.min_train:
            return
        if _HAS_SKLEARN:
            X = np.array(self.buffer)
            m = IsolationForest(
                contamination=self.contamination,
                random_state=42,
                n_estimators=100,
            )
            m.fit(X)
            self.model = m

    def score(self, aircraft: list[Aircraft]) -> list[MLAlert]:
        """Egitilmis modelle mevcut uçaklari skorla, aykirilari dondur."""
        if not self.trained:
            return []
        alerts: list[MLAlert] = []

        if _HAS_SKLEARN:
            rows, feats = [], []
            for ac in aircraft:
                f = features(ac)
                if f is not None:
                    rows.append(ac)
                    feats.append(f)
            if not feats:
                return []
            X = np.array(feats)
            scores = self.model.score_samples(X)   # dusuk = daha aykiri
            # MUTLAK esik: sabit-yuzde predict() yerine. Temiz trafikte cok az
            # flag; sadece gercekten uç davranis isaretlenir (yanlis-pozitif az).
            for ac, s in zip(rows, scores):
                if s < self.score_threshold:
                    alerts.append(MLAlert(
                        ac.icao24, ac.callsign, float(s),
                        f"İstatistiksel aykırı (skor {s:.3f}): filo geneline göre "
                        "sıradışı. Kesin tehdit değil — incele.",
                    ))
        else:
            alerts = self._score_mad(aircraft)
        return alerts

    # --- sklearn yoksa: robust z-score (MAD) yedegi -----------------------
    def _score_mad(self, aircraft: list[Aircraft]) -> list[MLAlert]:
        cols = list(zip(*self.buffer))  # her ozellik icin sutun
        med = [self._median(c) for c in cols]
        mad = [self._median([abs(x - med[i]) for x in c]) or 1e-9
               for i, c in enumerate(cols)]
        alerts = []
        for ac in aircraft:
            f = features(ac)
            if f is None:
                continue
            # en buyuk robust z-score
            zmax = max(abs(f[i] - med[i]) / (1.4826 * mad[i])
                       for i in range(len(f)))
            if zmax > 5.0:
                alerts.append(MLAlert(
                    ac.icao24, ac.callsign, -zmax,
                    f"Istatistiksel aykiri (z={zmax:.1f}): ozellik daginimindan uzak.",
                ))
        return alerts

    @staticmethod
    def _median(xs) -> float:
        s = sorted(xs)
        n = len(s)
        if n == 0:
            return 0.0
        m = n // 2
        return s[m] if n % 2 else (s[m - 1] + s[m]) / 2
