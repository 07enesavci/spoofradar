"""ADS-B Guard REST API (sifir ek bagimlilik — stdlib http.server).

Canli tespit sonuclarini JSON olarak sunar ki baska sistemler cekebilsin.
Dashboard'dan bagimsiz calisir; her istekte OpenSky'dan taze veri ceker.

Calistir:
    python api.py                 # 0.0.0.0:8700, Turkiye kutusu
    python api.py --port 9000 --region europe

Uc noktalar:
    GET /health                   saglik kontrolu
    GET /alerts?region=turkey     kural + ML alarmlari (JSON)
    GET /aircraft?region=turkey   tum uçaklar + güven skoru
    GET /jamming?region=turkey    GPS jamming supheli bolgeler
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from opensky import fetch_states
from detectors import analyze
from ml_detector import AnomalyModel
from jamming import build_grid, suspected_zones
from enrich import is_military, trust_score, source_label

REGIONS = {
    "turkey": (35.0, 25.0, 43.0, 45.0),
    "europe": (35.0, -10.0, 60.0, 30.0),
    "world": None,
}

# Tek paylasilan ML modeli (istekler arasi ogrenir)
_MODEL = AnomalyModel(min_train=200)
_PREV: dict = {}


def _snapshot(region: str):
    bbox = REGIONS.get(region, REGIONS["turkey"])
    current = fetch_states(bbox=bbox)
    global _PREV
    rule_alerts = analyze(_PREV, current)
    _MODEL.observe(current)
    if _MODEL.model is None or len(_MODEL.buffer) >= _MODEL.min_train:
        _MODEL.fit()
    ml_alerts = _MODEL.score(current)
    _PREV = {a.icao24: a for a in current if a.icao24}
    return current, rule_alerts, ml_alerts


def _alerts_json(region):
    current, rule_alerts, ml_alerts = _snapshot(region)
    return {
        "region": region, "aircraft_count": len(current),
        "rule_alerts": [
            {"icao24": a.icao24, "callsign": a.callsign, "kind": a.kind,
             "severity": a.severity, "detail": a.detail} for a in rule_alerts],
        "ml_alerts": [
            {"icao24": a.icao24, "callsign": a.callsign,
             "score": round(a.score, 3), "detail": a.detail} for a in ml_alerts],
    }


def _aircraft_json(region):
    current, rule_alerts, ml_alerts = _snapshot(region)
    high = {a.icao24 for a in rule_alerts if a.severity == "high"}
    warn = {a.icao24 for a in rule_alerts if a.severity in ("med", "low")}
    ml = {a.icao24 for a in ml_alerts}
    out = []
    for ac in current:
        if not ac.has_position:
            continue
        out.append({
            "icao24": ac.icao24, "callsign": ac.callsign,
            "lat": ac.lat, "lon": ac.lon, "alt": ac.baro_alt,
            "velocity": ac.velocity, "country": ac.country,
            "military": is_military(ac.icao24),
            "source": source_label(ac),
            "trust": trust_score(ac, ac.icao24 in high, ac.icao24 in warn,
                                 ac.icao24 in ml),
        })
    return {"region": region, "count": len(out), "aircraft": out}


def _jamming_json(region):
    current, _, _ = _snapshot(region)
    zones = suspected_zones(build_grid(current))
    return {"region": region, "suspected_zones": [
        {"lat": round(z.lat, 2), "lon": round(z.lon, 2),
         "ratio": round(z.ratio, 2), "degraded": z.degraded, "total": z.total}
        for z in zones]}


class Handler(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        region = q.get("region", ["turkey"])[0]
        try:
            if u.path == "/health":
                self._send({"status": "ok", "regions": list(REGIONS)})
            elif u.path == "/alerts":
                self._send(_alerts_json(region))
            elif u.path == "/aircraft":
                self._send(_aircraft_json(region))
            elif u.path == "/jamming":
                self._send(_jamming_json(region))
            else:
                self._send({"error": "unknown endpoint",
                            "endpoints": ["/health", "/alerts", "/aircraft", "/jamming"]}, 404)
        except Exception as e:
            self._send({"error": str(e)}, 500)

    def log_message(self, *a):
        pass  # sessiz


def main():
    p = argparse.ArgumentParser(description="ADS-B Guard REST API")
    p.add_argument("--port", type=int, default=8700)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--region", default="turkey", choices=list(REGIONS))
    args = p.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ADS-B Guard API: http://{args.host}:{args.port}")
    print("Uc noktalar: /health /alerts /aircraft /jamming  (?region=turkey|europe|world)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nDurduruldu.")


if __name__ == "__main__":
    main()
