"""Deniz trafigi (AIS) spoofing tespiti.

Gemiler de AIS ile konum/hiz/rota yayinlar — ADS-B gibi SIFRESIZ, IMZASIZ.
Ayni spoofing sorunu: sahte gemi, klon MMSI, imkansiz hiz, GPS jamming.

MIMARI (durust):
  Canli AIS verisi WebSocket gerektirir (aisstream.io ucretsiz, anahtar ister).
  Bu modul TESPIT mantigini icerir (ADS-B kodunu deniz'e uyarlar) ve canli
  besleme adaptorunu tanimlar. Anahtar verilirse baglanir; yoksa tespit
  fonksiyonlari yine test/besleme ile kullanilabilir.

  aisstream.io anahtari: ucretsiz kayit -> AISSTREAM_KEY ortam degiskeni.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from detectors import haversine

# Gemi hiz limiti: en hizli gemiler ~40 knot (~20 m/s). Ustu süpheli.
MAX_SHIP_SPEED_MS = 30.0     # ~58 knot — askeri/yaris ustu = süpheli
KNOT_TO_MS = 0.514444


@dataclass
class Ship:
    mmsi: str              # gemi kimligi (ADS-B'deki icao24 gibi)
    name: str
    lat: float | None
    lon: float | None
    sog: float | None      # speed over ground (knot)
    cog: float | None      # course over ground (derece)
    timestamp: float
    ship_type: str = ""

    @property
    def has_position(self):
        return self.lat is not None and self.lon is not None

    @property
    def sog_ms(self):
        return self.sog * KNOT_TO_MS if self.sog is not None else None


@dataclass
class ShipAlert:
    mmsi: str
    name: str
    kind: str
    detail: str
    severity: str


def check_ship_speed(prev: Ship, cur: Ship) -> ShipAlert | None:
    """Konum sicramasi ima edilen hiz gemi limitini asiyor mu?"""
    if not (prev.has_position and cur.has_position):
        return None
    dt = cur.timestamp - prev.timestamp
    if dt < 1:
        return None
    dist = haversine(prev.lat, prev.lon, cur.lat, cur.lon)
    implied = dist / dt
    if implied > MAX_SHIP_SPEED_MS:
        return ShipAlert(
            cur.mmsi, cur.name, "impossible_speed",
            f"{implied/KNOT_TO_MS:.0f} knot ima edildi ({dist/1852:.0f} nm / "
            f"{dt:.0f} s). Gemi için imkansız = spoofing şüphesi.", "high")
    return None


def find_duplicate_mmsi(ships: list[Ship]) -> list[ShipAlert]:
    """Ayni MMSI iki uzak konumda = klon gemi kimligi."""
    seen: dict[str, Ship] = {}
    alerts = []
    for s in ships:
        if not s.mmsi or not s.has_position:
            continue
        if s.mmsi in seen:
            d = haversine(s.lat, s.lon, seen[s.mmsi].lat, seen[s.mmsi].lon)
            if d > 10000:  # 10 km
                alerts.append(ShipAlert(
                    s.mmsi, s.name, "duplicate_mmsi",
                    f"Aynı MMSI iki uzak konumda ({d/1852:.0f} nm). Klon kimlik.",
                    "high"))
        else:
            seen[s.mmsi] = s
    return alerts


def analyze_ships(prev_by_mmsi: dict[str, Ship],
                  current: list[Ship]) -> list[ShipAlert]:
    """Gemi trafigini analiz et (ADS-B analyze'in deniz karsiligi)."""
    alerts = []
    for s in current:
        prev = prev_by_mmsi.get(s.mmsi)
        if prev:
            a = check_ship_speed(prev, s)
            if a:
                alerts.append(a)
    alerts.extend(find_duplicate_mmsi(current))
    return alerts


def ais_available() -> bool:
    """Canli AIS besleme (aisstream.io anahtari) ayarli mi?"""
    return bool(os.environ.get("AISSTREAM_KEY"))


def fetch_ships(bbox, seconds: float = 8.0, max_ships: int = 400) -> list[Ship]:
    """aisstream.io WebSocket'ini KISA sure dinle, gemi anlik goruntusu topla.

    Dashboard bunu her yenilemede cagirir (uçak fetch_states gibi). WebSocket
    surekli akar; biz birkac saniye dinleyip o an gelen gemileri toplariz.
    Anahtar/paket yoksa bos liste doner (araç yine calisir).

    bbox = (lamin, lomin, lamax, lomax)
    """
    ships, _ = fetch_ships_debug(bbox, seconds, max_ships)
    return ships


def fetch_ships_debug(bbox, seconds: float = 8.0, max_ships: int = 400):
    """fetch_ships + durum bilgisi. Doner: (gemiler, durum_mesaji).

    durum: teshis icin — anahtar/paket/baglanti/gemi durumu. Sessiz hata
    yerine gercek sebebi gorunur yapar.
    """
    key = os.environ.get("AISSTREAM_KEY")
    if not key:
        return [], "ANAHTAR YOK: AISSTREAM_KEY ayarlı değil."
    try:
        import json
        import time as _t
        import websocket  # websocket-client
    except ImportError:
        return [], "PAKET YOK: 'pip install websocket-client' gerekli."

    lamin, lomin, lamax, lomax = bbox
    # aisstream BoundingBoxes: [[[guney-lat, bati-lon], [kuzey-lat, dogu-lon]]]
    sub = {
        "APIKey": key,
        "BoundingBoxes": [[[lamin, lomin], [lamax, lomax]]],
        "FilterMessageTypes": ["PositionReport"],
    }
    ships: dict[str, Ship] = {}
    ws = None
    status = "OK"
    got_any_msg = False
    try:
        ws = websocket.create_connection("wss://stream.aisstream.io/v0/stream",
                                         timeout=8)
        ws.send(json.dumps(sub))
        end = _t.time() + seconds
        ws.settimeout(3)
        while _t.time() < end and len(ships) < max_ships:
            try:
                raw = ws.recv()
            except Exception:
                continue
            got_any_msg = True
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            # aisstream hata mesaji (gecersiz anahtar vs) — genelde 'error' alani
            if isinstance(msg, dict) and msg.get("error"):
                status = f"AISSTREAM HATASI: {msg['error']}"
                break
            if msg.get("MessageType") != "PositionReport":
                continue
            try:
                pr = msg["Message"]["PositionReport"]
                meta = msg.get("MetaData", {})
            except (KeyError, TypeError):
                continue
            mmsi = str(pr.get("UserID", ""))
            if not mmsi:
                continue
            ships[mmsi] = Ship(
                mmsi=mmsi,
                name=(meta.get("ShipName") or "").strip(),
                lat=pr.get("Latitude"), lon=pr.get("Longitude"),
                sog=pr.get("Sog"), cog=pr.get("Cog"),
                timestamp=_t.time())
    except Exception as e:
        status = f"BAĞLANTI HATASI: {e}"
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass

    result = list(ships.values())
    if result:
        status = f"OK: {len(result)} gemi alındı."
    elif status == "OK":
        if not got_any_msg:
            status = ("Bağlandı ama hiç mesaj gelmedi — anahtar geçersiz olabilir "
                      "veya bölgede gemi yok. Süreyi artırıp tekrar dene.")
        else:
            status = "Mesaj geldi ama bu bölgede konum-raporu yok (deniz az)."
    return result, status


# --- Canli besleme adaptoru (aisstream.io WebSocket) -----------------------
def stream_ships(bbox, on_ship, duration: int = 60):
    """aisstream.io'dan canli gemi verisi ak. Anahtar + websocket gerekir.

    bbox = (lamin, lomin, lamax, lomax). on_ship(Ship) her mesajda cagrilir.
    websocket-client paketi yoksa veya anahtar yoksa nazikce cikar.
    """
    key = os.environ.get("AISSTREAM_KEY")
    if not key:
        print("AISSTREAM_KEY yok — canli AIS beslemesi atlandi.")
        return
    try:
        import json
        import websocket  # websocket-client
    except ImportError:
        print("websocket-client paketi gerekli: pip install websocket-client")
        return
    import time as _t
    lamin, lomin, lamax, lomax = bbox
    sub = {
        "APIKey": key,
        "BoundingBoxes": [[[lamin, lomin], [lamax, lomax]]],
        "FilterMessageTypes": ["PositionReport"],
    }
    ws = websocket.create_connection("wss://stream.aisstream.io/v0/stream",
                                     timeout=10)
    ws.send(json.dumps(sub))
    end = _t.time() + duration
    while _t.time() < end:
        try:
            msg = json.loads(ws.recv())
            if msg.get("MessageType") == "PositionReport":
                pr = msg["Message"]["PositionReport"]
                meta = msg["MetaData"]
                on_ship(Ship(
                    mmsi=str(pr.get("UserID", "")),
                    name=meta.get("ShipName", "").strip(),
                    lat=pr.get("Latitude"), lon=pr.get("Longitude"),
                    sog=pr.get("Sog"), cog=pr.get("Cog"),
                    timestamp=_t.time()))
        except Exception:
            break
    ws.close()
