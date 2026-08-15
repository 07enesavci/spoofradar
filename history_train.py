"""Gecmis veri toplama + kalici ML modeli egitimi.

Anlik-ogrenme yerine OLGUN model: bir sure canli veri biriktir, uzerine
IsolationForest egit, diske kaydet. Dashboard bu kayitli modeli yukleyip
ilk saniyeden itibaren olgun tespit yapar (isinma beklemez).

Kullanim:
    python history_train.py collect --minutes 30    # 30 dk veri topla
    python history_train.py train                    # toplanan veriyle egit
    python history_train.py info                      # kayitli model bilgisi

Model 'model.pkl', veri 'training_data.csv' olarak kaydedilir.
"""

from __future__ import annotations

import argparse
import csv
import os
import pickle
import time

from opensky import fetch_states
from ml_detector import features

DATA_PATH = os.path.join(os.path.dirname(__file__), "training_data.csv")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")

REGIONS = {
    "turkey": (35.0, 25.0, 43.0, 45.0),
    "europe": (35.0, -10.0, 60.0, 30.0),
    "world": None,
}


def collect(minutes: float, region: str, interval: int = 30):
    """Canli veriyi belirli sure topla, ozellik vektorlerini CSV'ye ekle."""
    bbox = REGIONS.get(region)
    end = time.time() + minutes * 60
    n = 0
    new_file = not os.path.exists(DATA_PATH)
    with open(DATA_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["velocity", "vertical_rate", "baro_alt", "alt_diff", "track"])
        while time.time() < end:
            try:
                ac = fetch_states(bbox=bbox)
            except Exception as e:
                print(f"  cekme hatasi: {e}")
                time.sleep(interval)
                continue
            for a in ac:
                fe = features(a)
                if fe is not None:
                    w.writerow(fe)
                    n += 1
            f.flush()
            remaining = int(end - time.time())
            print(f"  toplandi: {n} ornek, kalan ~{remaining}s")
            time.sleep(interval)
    print(f"Toplam {n} ornek {DATA_PATH}'e eklendi.")


def train(contamination: float = 0.02):
    """Toplanan veriyle IsolationForest egit, diske kaydet."""
    try:
        import numpy as np
        from sklearn.ensemble import IsolationForest
    except ImportError:
        print("HATA: scikit-learn/numpy gerekli.")
        return
    if not os.path.exists(DATA_PATH):
        print(f"HATA: {DATA_PATH} yok — once 'collect' calistir.")
        return
    rows = []
    with open(DATA_PATH) as f:
        r = csv.reader(f)
        next(r, None)  # baslik
        for row in r:
            try:
                rows.append([float(x) for x in row])
            except ValueError:
                continue
    if len(rows) < 100:
        print(f"HATA: yetersiz veri ({len(rows)} ornek, en az 100 gerek).")
        return
    X = np.array(rows)
    model = IsolationForest(contamination=contamination, random_state=42,
                            n_estimators=200)
    model.fit(X)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"model": model, "n_samples": len(rows),
                     "trained_at": time.time()}, f)
    print(f"Model egitildi: {len(rows)} ornek, {MODEL_PATH}'e kaydedildi.")


def info():
    """Kayitli model bilgisi."""
    if not os.path.exists(MODEL_PATH):
        print("Kayitli model yok.")
        return
    with open(MODEL_PATH, "rb") as f:
        d = pickle.load(f)
    age_h = (time.time() - d["trained_at"]) / 3600
    print(f"Model: {d['n_samples']} ornekle egitilmis, {age_h:.1f} saat once.")


def load_model():
    """Dashboard icin: kayitli modeli yukle (yoksa None)."""
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        with open(MODEL_PATH, "rb") as f:
            return pickle.load(f)["model"]
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser(description="ADS-B Guard gecmis egitim")
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("collect")
    c.add_argument("--minutes", type=float, default=30)
    c.add_argument("--region", default="turkey", choices=list(REGIONS))
    c.add_argument("--interval", type=int, default=30)
    t = sub.add_parser("train")
    t.add_argument("--contamination", type=float, default=0.02)
    sub.add_parser("info")
    args = p.parse_args()

    if args.cmd == "collect":
        collect(args.minutes, args.region, args.interval)
    elif args.cmd == "train":
        train(args.contamination)
    elif args.cmd == "info":
        info()
    else:
        p.print_help()


if __name__ == "__main__":
    main()
