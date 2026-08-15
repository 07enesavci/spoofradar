"""Bildirim: Telegram / Discord ile alarm gonderimi.

Yapilandirilmissa calisir, yoksa nazikce atlar. Ortam degiskenleri:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (Telegram icin)
  DISCORD_WEBHOOK_URL                    (Discord icin)

Kullanim (kod icinden):
    from notify import notify_high_alerts
    notify_high_alerts(rule_alerts)

Ya da tek seferlik test:
    python notify.py "test mesaji"
"""

from __future__ import annotations

import os
import sys

import requests

_TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
_TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")
_DISCORD = os.environ.get("DISCORD_WEBHOOK_URL")


def configured() -> dict:
    """Hangi kanallar ayarli?"""
    return {"telegram": bool(_TG_TOKEN and _TG_CHAT), "discord": bool(_DISCORD)}


def send(text: str) -> dict:
    """Metni ayarli tum kanallara gonder. Sonuc: kanal -> basari/atlandi."""
    result = {}
    if _TG_TOKEN and _TG_CHAT:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{_TG_TOKEN}/sendMessage",
                json={"chat_id": _TG_CHAT, "text": text, "parse_mode": "Markdown"},
                timeout=10)
            result["telegram"] = "ok" if r.ok else f"hata {r.status_code}"
        except Exception as e:
            result["telegram"] = f"hata: {e}"
    else:
        result["telegram"] = "ayarlanmadi"

    if _DISCORD:
        try:
            r = requests.post(_DISCORD, json={"content": text}, timeout=10)
            result["discord"] = "ok" if r.ok else f"hata {r.status_code}"
        except Exception as e:
            result["discord"] = f"hata: {e}"
    else:
        result["discord"] = "ayarlanmadi"

    return result


def notify_high_alerts(rule_alerts, region: str = "-") -> dict | None:
    """Yuksek-onem alarmlari (isinlanma, klon, acil) bildir.

    Hicbir yuksek alarm yoksa None doner (bildirim yok).
    """
    high = [a for a in rule_alerts if a.severity == "high"]
    if not high:
        return None
    lines = [f"🛰️ *ADS-B Guard* — {region} bölgesinde {len(high)} yüksek-önem alarm:"]
    for a in high[:10]:
        lines.append(f"• `{a.icao24}` {a.callsign or ''}: {a.detail}")
    return send("\n".join(lines))


if __name__ == "__main__":
    print("Ayarli kanallar:", configured())
    msg = sys.argv[1] if len(sys.argv) > 1 else "ADS-B Guard test bildirimi 🛰️"
    print("Gonderim sonucu:", send(msg))
