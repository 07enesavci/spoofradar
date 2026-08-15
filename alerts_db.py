"""Alarm gecmisi - SQLite kalici kayit.

Her turdaki alarmlari diske yazar, gecmis sorgulanabilir olur:
  - log_alerts: alarmlari kaydet
  - recent_count: son N saatteki alarm sayisi
  - hourly_counts: saat bazinda alarm dagilimi (trend grafigi icin)
  - top_offenders: en cok alarm ureten uçaklar
"""

from __future__ import annotations

import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "alerts.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            ts REAL, icao24 TEXT, callsign TEXT,
            kind TEXT, severity TEXT, detail TEXT,
            lat REAL, lon REAL
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_ts ON alerts(ts)")
    return c


def log_alerts(alerts, positions: dict) -> None:
    """Alarm listesini kaydet. positions: icao24 -> (lat, lon)."""
    if not alerts:
        return
    now = time.time()
    rows = []
    for a in alerts:
        lat, lon = positions.get(a.icao24, (None, None))
        rows.append((now, a.icao24, a.callsign, a.kind, a.severity, a.detail, lat, lon))
    c = _conn()
    with c:
        c.executemany("INSERT INTO alerts VALUES (?,?,?,?,?,?,?,?)", rows)
    c.close()


def recent_count(hours: float = 24) -> int:
    since = time.time() - hours * 3600
    c = _conn()
    n = c.execute("SELECT COUNT(*) FROM alerts WHERE ts >= ?", (since,)).fetchone()[0]
    c.close()
    return n


def hourly_counts(hours: int = 24) -> list[tuple[str, int]]:
    """Son 'hours' saat icin saat basi alarm sayisi (etiket, sayi)."""
    since = time.time() - hours * 3600
    c = _conn()
    rows = c.execute(
        "SELECT CAST((? - ts) / 3600 AS INT) AS h, COUNT(*) "
        "FROM alerts WHERE ts >= ? GROUP BY h",
        (time.time(), since),
    ).fetchall()
    c.close()
    buckets = {int(h): n for h, n in rows}
    # saat -h once ... simdi; grafik icin eskiden yeniye
    out = []
    for h in range(hours - 1, -1, -1):
        out.append((f"-{h}s", buckets.get(h, 0)))
    return out


def alerts_in_window(hours_ago_start: float, hours_ago_end: float) -> list[tuple]:
    """Belirli zaman penceresindeki konumlu alarmlar (zaman makinesi icin).

    Ornek: son 6-4 saat arasi = alerts_in_window(6, 4).
    Doner: (ts, icao24, callsign, kind, severity, lat, lon)
    """
    now = time.time()
    t_start = now - hours_ago_start * 3600
    t_end = now - hours_ago_end * 3600
    c = _conn()
    rows = c.execute(
        "SELECT ts, icao24, callsign, kind, severity, lat, lon FROM alerts "
        "WHERE ts >= ? AND ts <= ? AND lat IS NOT NULL ORDER BY ts",
        (t_start, t_end),
    ).fetchall()
    c.close()
    return rows


def top_offenders(hours: float = 24, limit: int = 5) -> list[tuple]:
    """En cok alarm ureten uçaklar (icao24, callsign, sayi)."""
    since = time.time() - hours * 3600
    c = _conn()
    rows = c.execute(
        "SELECT icao24, callsign, COUNT(*) n FROM alerts "
        "WHERE ts >= ? GROUP BY icao24 ORDER BY n DESC LIMIT ?",
        (since, limit),
    ).fetchall()
    c.close()
    return rows
