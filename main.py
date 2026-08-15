"""ADS-B Guard - canli ADS-B anomali / spoofing izleyici.

OpenSky'dan belirli araliklarla uçak durumu çeker, ardisik snapshot'lari
karsilastirir ve süpheli / imkansiz gecisleri konsola flaglar.

Kullanim:
    python main.py                 # tum dunya
    python main.py --turkey        # Turkiye civari kutu
    python main.py --interval 15   # 15 saniyede bir cek
"""

from __future__ import annotations

import argparse
import time

from opensky import Aircraft, fetch_states
from detectors import Alert, analyze
from ml_detector import AnomalyModel, MLAlert

# Onceden tanimli cografi kutular (lamin, lomin, lamax, lomax)
BBOXES = {
    "turkey": (35.0, 25.0, 43.0, 45.0),
    "europe": (35.0, -10.0, 60.0, 30.0),
}

SEV_COLOR = {"high": "\033[91m", "med": "\033[93m", "low": "\033[90m"}
RESET = "\033[0m"


def print_alert(a: Alert) -> None:
    color = SEV_COLOR.get(a.severity, "")
    tag = a.severity.upper().ljust(4)
    cs = a.callsign or "-------"
    print(f"{color}[{tag}] {a.icao24} {cs:8} {a.kind:18} {a.detail}{RESET}")


def print_ml_alert(a: MLAlert) -> None:
    cs = a.callsign or "-------"
    print(f"\033[95m[ML  ] {a.icao24} {cs:8} {'ml_anomaly':18} {a.detail}\033[0m")


def run(bbox=None, interval=15, use_ml=True, refit_every=10) -> None:
    prev_by_icao: dict[str, Aircraft] = {}
    model = AnomalyModel() if use_ml else None
    loop_i = 0
    print(f"ADS-B Guard basladi. Aralik={interval}s  Kutu={bbox or 'tum dunya'}")
    if model:
        print(f"ML backend: {model.backend} (isinma icin veri topluyor...)")
    print("Ctrl+C ile dur.\n")

    while True:
        loop_start = time.time()
        loop_i += 1
        try:
            current = fetch_states(bbox=bbox)
        except Exception as e:
            print(f"[hata] veri cekilemedi: {e}")
            time.sleep(interval)
            continue

        with_pos = [a for a in current if a.has_position]
        alerts = analyze(prev_by_icao, current)

        ml_alerts: list[MLAlert] = []
        if model:
            model.observe(current)
            if loop_i % refit_every == 0 or (model.trained is False and model.model is None):
                model.fit()
            ml_alerts = model.score(current)

        ts = time.strftime("%H:%M:%S")
        ml_state = "-"
        if model:
            ml_state = "hazir" if model.trained else "isiniyor"
        print(f"--- {ts}  uçak={len(current)} (konumlu={len(with_pos)})  "
              f"kural-alarm={len(alerts)}  ml-alarm={len(ml_alerts)}  ml={ml_state} ---")
        for a in alerts:
            print_alert(a)
        for m in ml_alerts:
            print_ml_alert(m)

        # sonraki tur icin durumu guncelle
        prev_by_icao = {a.icao24: a for a in current if a.icao24}

        elapsed = time.time() - loop_start
        time.sleep(max(0, interval - elapsed))


def main() -> None:
    p = argparse.ArgumentParser(description="ADS-B anomali izleyici")
    p.add_argument("--turkey", action="store_true", help="Turkiye kutusu")
    p.add_argument("--europe", action="store_true", help="Avrupa kutusu")
    p.add_argument("--interval", type=int, default=15, help="cekme araligi (s)")
    p.add_argument("--no-ml", action="store_true", help="ML katmanini kapat")
    args = p.parse_args()

    bbox = None
    if args.turkey:
        bbox = BBOXES["turkey"]
    elif args.europe:
        bbox = BBOXES["europe"]

    try:
        run(bbox=bbox, interval=args.interval, use_ml=not args.no_ml)
    except KeyboardInterrupt:
        print("\nDurduruldu.")


if __name__ == "__main__":
    main()
