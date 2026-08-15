"""PDF/HTML olay raporu (sifir ek bagimlilik).

Kendinden-yeterli HTML rapor uretir — tarayicida acilir, Ctrl+P ile PDF
kaydedilir. reportlab gibi agir bagimlilik gerektirmez.

Kullanim (kod icinden):
    from report import build_html_report
    path = build_html_report(current, rule_alerts, ml_alerts, zones, region)

Tek seferlik (canli veriyle):
    python report.py            # rapor.html uretir
"""

from __future__ import annotations

import html
import os
import time


def _rows(items, cols):
    out = []
    for it in items:
        tds = "".join(f"<td>{html.escape(str(c))}</td>" for c in it)
        out.append(f"<tr>{tds}</tr>")
    header = "".join(f"<th>{html.escape(c)}</th>" for c in cols)
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(out)}</tbody></table>"


def build_html_report(current, rule_alerts, ml_alerts, zones, region="-",
                      out_path="rapor.html") -> str:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    high = [a for a in rule_alerts if a.severity == "high"]

    rule_tbl = _rows(
        [(a.severity, a.icao24, a.callsign or "-", a.kind, a.detail) for a in rule_alerts],
        ["Önem", "ICAO24", "Çağrı", "Tür", "Açıklama"]) if rule_alerts else "<p>Yok.</p>"
    ml_tbl = _rows(
        [(a.icao24, a.callsign or "-", round(a.score, 3), a.detail) for a in ml_alerts],
        ["ICAO24", "Çağrı", "Skor", "Açıklama"]) if ml_alerts else "<p>Yok.</p>"
    zone_tbl = _rows(
        [(round(z.lat, 1), round(z.lon, 1), f"{z.ratio*100:.0f}%", z.degraded, z.total)
         for z in zones],
        ["Enlem", "Boylam", "Bozulma", "Bozulmuş", "Toplam"]) if zones else "<p>Yok.</p>"

    doc = f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>SpoofRadar Raporu — {region}</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 40px; color: #1a2332;
          background: #fff; }}
  h1 {{ color: #0d5a7a; border-bottom: 3px solid #22a7c9; padding-bottom: 8px; }}
  h2 {{ color: #0d5a7a; margin-top: 28px; }}
  .meta {{ color: #666; font-size: 14px; }}
  .summary {{ background: #f0f8fb; border-left: 4px solid #22a7c9;
              padding: 12px 16px; margin: 16px 0; }}
  .high {{ color: #c0392b; font-weight: bold; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13px; }}
  th, td {{ border: 1px solid #d0d7de; padding: 6px 10px; text-align: left; }}
  th {{ background: #eef4f7; }}
  .foot {{ margin-top: 30px; color: #888; font-size: 12px; }}
  @media print {{ body {{ margin: 12mm; }} }}
</style></head><body>
<h1>🛰️ SpoofRadar — Tehdit Raporu</h1>
<p class="meta">Bölge: <b>{region}</b> · Üretim: {ts} · Veri: OpenSky Network (halka açık)</p>
<div class="summary">
  <b>Özet:</b> {len(current)} uçak izlendi.
  <span class="high">{len(high)} yüksek-önem</span> kural alarmı,
  {len(ml_alerts)} ML aykırı, {len(zones)} GPS-jamming şüpheli bölge.
</div>
<h2>Kural alarmları (fiziksel/mantıksal imkansızlıklar)</h2>{rule_tbl}
<h2>ML alarmları (öğrenilmiş normalden sapanlar)</h2>{ml_tbl}
<h2>GPS jamming şüpheli bölgeler</h2>{zone_tbl}
<p class="foot">Bu bir savunma-amaçlı analiz aracıdır. Tespitler ADS-B verisine
dayalı <b>şüphe</b> göstergeleridir, kesin kanıt değildir. PDF için Ctrl+P → Kaydet.</p>
</body></html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return os.path.abspath(out_path)


if __name__ == "__main__":
    from opensky import fetch_states
    from detectors import analyze
    from jamming import build_grid, suspected_zones
    ac = fetch_states(bbox=(35.0, 25.0, 43.0, 45.0))
    al = analyze({}, ac)
    zones = suspected_zones(build_grid(ac))
    path = build_html_report(ac, al, [], zones, "Turkiye")
    print("Rapor yazildi:", path)
