"""AI katmani: Claude ile dogal dil tehdit raporu + dogal dil sorgu.

ANAHTAR YOKSA CALISIR: anthropic paketi veya ANTHROPIC_API_KEY yoksa
sablon-tabanli ozet uretilir (araç savunma araci, cevrimdisi de calismali).
Anahtar varsa Claude Opus 5 ile akici Turkce tehdit raporu yazilir.

Ortam:
  ANTHROPIC_API_KEY=...   (opsiyonel)
"""

from __future__ import annotations

import os

MODEL = "claude-opus-5"

try:
    import anthropic
    _HAS_SDK = True
except Exception:
    _HAS_SDK = False


def ai_available() -> bool:
    """Claude API kullanilabilir mi (paket + anahtar)?"""
    return _HAS_SDK and bool(os.environ.get("ANTHROPIC_API_KEY"))


def _summary_stats(current, rule_alerts, ml_alerts, zones, events, breaches):
    high = [a for a in rule_alerts if a.severity == "high"]
    kinds = {}
    for a in rule_alerts:
        kinds[a.kind] = kinds.get(a.kind, 0) + 1
    return {
        "ucak": len(current),
        "kural_alarm": len(rule_alerts),
        "yuksek_alarm": len(high),
        "ml_alarm": len(ml_alerts),
        "jamming_bolge": len(zones),
        "olay": len(events),
        "geofence": len(breaches),
        "kural_tipleri": kinds,
    }


def template_report(current, rule_alerts, ml_alerts, zones, events, breaches) -> str:
    """Anahtar yokken sablon-tabanli Turkce ozet."""
    s = _summary_stats(current, rule_alerts, ml_alerts, zones, events, breaches)
    lines = [f"**Tehdit özeti** — {s['ucak']} uçak izleniyor."]

    if s["yuksek_alarm"]:
        lines.append(
            f"🔴 {s['yuksek_alarm']} yüksek-önem kural alarmı: fiziksel olarak "
            "imkansız hareketler tespit edildi (güçlü spoofing şüphesi).")
    if s["ml_alarm"]:
        lines.append(
            f"🟣 {s['ml_alarm']} uçak öğrenilmiş normal davranıştan sapıyor "
            "(ML aykırı — inceleme önerilir).")
    if s["jamming_bolge"]:
        lines.append(
            f"📡 {s['jamming_bolge']} bölgede GPS jamming şüphesi "
            "(baro-GNSS irtifa tutarsızlığı yoğun).")
    if s["olay"]:
        lines.append(f"⚠️ {s['olay']} olay: karanlık uçak (sinyal kesilmesi) veya "
                     "tehlikeli yakınlaşma.")
    if s["geofence"]:
        lines.append(f"🛑 {s['geofence']} coğrafi-çit ihlali (havaalanı/yasak bölge).")

    if len(lines) == 1:
        lines.append("Trafik temiz görünüyor — yüksek-önem tehdit yok.")

    if s["kural_tipleri"]:
        parts = ", ".join(f"{k}×{v}" for k, v in s["kural_tipleri"].items())
        lines.append(f"\n_Kural dağılımı: {parts}_")

    lines.append("\n_(Şablon raporu — ANTHROPIC_API_KEY ayarlarsan Claude "
                 "ayrıntılı doğal dil analizi yazar.)_")
    return "\n\n".join(lines)


def claude_report(current, rule_alerts, ml_alerts, zones, events, breaches,
                  region: str) -> str:
    """Claude Opus 5 ile akici Turkce tehdit raporu."""
    s = _summary_stats(current, rule_alerts, ml_alerts, zones, events, breaches)

    # Alarm ornekleri (ilk birkac), modele baglam ver
    sample_rule = [f"- {a.severity} {a.kind} {a.icao24} {a.callsign}: {a.detail}"
                   for a in rule_alerts[:8]]
    sample_zone = [f"- lat {z.lat:.1f} lon {z.lon:.1f} bozulma %{z.ratio*100:.0f} "
                   f"({z.degraded}/{z.total})" for z in zones[:5]]
    sample_evt = [f"- {e.kind} {e.icao24}: {e.detail}" for e in events[:5]]

    context = (
        f"Bölge: {region}\n"
        f"İstatistik: {s}\n\n"
        f"Kural alarmları:\n" + ("\n".join(sample_rule) or "yok") + "\n\n"
        f"GPS jamming şüpheli bölgeler:\n" + ("\n".join(sample_zone) or "yok") + "\n\n"
        f"Olaylar:\n" + ("\n".join(sample_evt) or "yok")
    )

    system = (
        "Sen bir hava sahası siber-güvenlik analistisin. ADS-B spoofing tespit "
        "sisteminin çıktısını okuyup KISA, net bir Türkçe tehdit raporu yaz. "
        "En kritik bulguyu öne al. Kesin olmayan şeyleri 'şüphe' olarak belirt "
        "(veri sadece ADS-B, kesin kanıt değil). Abartma, spekülasyon yapma. "
        "3-6 cümle. Markdown kullan."
    )

    client = anthropic.Anthropic()
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=system,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content":
                       f"Şu tespit çıktısını raporla:\n\n{context}"}],
        )
    except Exception as e:
        return f"_(Claude çağrısı başarısız: {e}. Şablon rapora dönülüyor.)_\n\n" + \
               template_report(current, rule_alerts, ml_alerts, zones, events, breaches)

    if resp.stop_reason == "refusal":
        return "_(Claude güvenlik gerekçesiyle yanıt vermedi. Şablon rapor:)_\n\n" + \
               template_report(current, rule_alerts, ml_alerts, zones, events, breaches)

    return next((b.text for b in resp.content if b.type == "text"), "").strip()


def generate_report(current, rule_alerts, ml_alerts, zones, events, breaches,
                    region: str = "-") -> str:
    """Uygun yolu seç: Claude varsa Claude, yoksa şablon."""
    if ai_available():
        return claude_report(current, rule_alerts, ml_alerts, zones, events,
                             breaches, region)
    return template_report(current, rule_alerts, ml_alerts, zones, events, breaches)
