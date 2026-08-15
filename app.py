"""ADS-B Guard - web dashboard (Streamlit).

Canli uçak trafigini harita uzerinde gosterir, kural + ML alarmlarini
isaretler, GPS jamming supheli bolgeleri cikarir.

Calistir:
    streamlit run app.py
"""

from __future__ import annotations

import math
import os
import time

import pandas as pd
import pydeck as pdk
import streamlit as st

# KRITIK: Streamlit Cloud secrets.toml -> st.secrets'e gider, os.environ'a
# DEGIL. Modullerimiz (opensky, ai_report, notify, ais) os.environ okur.
# Koprü: secrets'i environ'a kopyala (deploy'da anahtarlar calissin).
try:
    for _k in ("OPENSKY_USER", "OPENSKY_PASS", "ANTHROPIC_API_KEY",
               "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL",
               "AISSTREAM_KEY"):
        if _k in st.secrets and st.secrets[_k]:
            os.environ.setdefault(_k, str(st.secrets[_k]))
except Exception:
    pass  # yerel: secrets.toml yoksa sorun degil

from opensky import Aircraft, fetch_states, authenticated
from detectors import analyze, EMERGENCY_SQUAWK
from ml_detector import AnomalyModel
from jamming import build_grid, suspected_zones
from quota import QuotaTracker, credit_cost
from enrich import is_military, trust_score, trust_label, source_label
from verify import verify, VERDICT_LABEL
from events import find_dark, find_conflicts
from geofence import check_zones, DEFAULT_ZONES
from fingerprint import FingerprintStore
from simulator import inject, SCENARIO_LABELS, generate_normal_traffic
import adsb_lol
from report import build_html_report
from mlat import (Receiver, solve_tdoa, geodetic_to_ecef, cross_check, C,
                  _HAS_NUMPY)
from callsign_db import validate_callsign
from predict import trajectory_deviation, aircraft_type
from ais import Ship, analyze_ships, ais_available
# drone.py modulu kalir (yol haritasi — RemoteID yerel alici gerektirir),
# dashboard'dan kaldirildi (canli veri uzaktan cekilemez).
import ai_report
import notify
import alerts_db
import math as _m
import random as _rnd

# --- Sabitler --------------------------------------------------------------
# Yenileme SABIT. Anonim OpenSky kotasi (~400 kredi/gun) 10s'yi kaldirmaz;
# Otomatik yenileme araligi. 30s = harita cok sik yeniden cizilmez ('ziplama'
# azalir), kota da yavas biter. Otomatik varsayilan KAPALI zaten.
REFRESH_SECONDS = 30

BBOXES = {
    "Turkiye": (35.0, 25.0, 43.0, 45.0),
    "Avrupa": (35.0, -10.0, 60.0, 30.0),
    "Tum dunya": None,
}

# SABIT harita merkezi/zoom (bolge basina). Harita her yenilemede uçak
# ortalamasina KAYMASIN diye df.mean() yerine bunu kullaniriz — boylece
# kullanicinin zoom/kaydirmasi bozulmaz, harita yerinde kalir.
MAP_VIEW = {
    "Turkiye": (39.0, 35.0, 5),
    "Avrupa": (48.0, 10.0, 3),
    "Tum dunya": (20.0, 0.0, 1),
}

# Uçak = kucuk ucgen, uçus yonune donuk. deck.gl PolygonLayer ile cizilir:
# saf geometri, resim/texture YOK (IconLayer data-URI decode edemiyordu).
def plane_triangle(lat, lon, track_deg, size_m=6500.0):
    """Uçak konumu + yonunden ucgen kose noktalari [[lon,lat],...] uret."""
    th = math.radians(track_deg or 0.0)
    # yerel (dogu=x, kuzey=y) metre koordinatinda ucgen: burun ileri
    pts = [(0.0, size_m), (-size_m * 0.55, -size_m * 0.6),
           (size_m * 0.55, -size_m * 0.6)]
    coslat = max(0.1, math.cos(math.radians(lat)))
    out = []
    for x, y in pts:
        # track = kuzeyden saat yonu; noktalari saat yonu dondur
        e = x * math.cos(th) + y * math.sin(th)
        n = -x * math.sin(th) + y * math.cos(th)
        out.append([lon + e / (111320.0 * coslat), lat + n / 111320.0])
    return out

# Kural tipi → insan-okur aciklama
KIND_LABELS = {
    "impossible_speed": "İmkansız hız (ışınlanma)",
    "altitude_jump": "Ani irtifa sıçraması",
    "duplicate_icao": "Klon kimlik (aynı uçak 2 konumda)",
    "malformed_callsign": "Bozuk çağrı işareti",
    "emergency_squawk": "Acil durum kodu (squawk)",
}
SEV_LABEL = {"high": "🔴 Yüksek", "med": "🟠 Orta", "low": "⚪ Düşük"}
SEV_RANK = {"high": 0, "med": 1, "low": 2}

st.set_page_config(page_title="ADS-B Guard", layout="wide", page_icon="🛰️")

# --- Harekat merkezi temasi (glow, monospace, radar hissi) -----------------
st.markdown("""
<style>
.stApp { background: radial-gradient(circle at 50% 0%, #0d1b2e 0%, #070d17 70%); }
h1, h2, h3 { color: #22d3ee !important; letter-spacing: 0.5px;
             text-shadow: 0 0 8px rgba(34,211,238,0.35); font-family: monospace; }
[data-testid="stMetricValue"] { color: #e6f7ff; font-family: monospace;
             text-shadow: 0 0 6px rgba(34,211,238,0.25); }
[data-testid="stMetricLabel"] { color: #7fb8cc; }
.stAlert { border-left: 3px solid #22d3ee; }
section[data-testid="stSidebar"] { background: #0a1524; border-right: 1px solid #12324a; }
[data-testid="stCaptionContainer"] { color: #6c8ba3; }
/* Sekme cubugu: 7 sekme yatay sigmazsa ALT SATIRA SAR — hepsi gorunur */
[data-testid="stTabs"] [role="tablist"] { flex-wrap: wrap; gap: 4px; }
[data-testid="stTabs"] [role="tab"] {
  background: rgba(18,50,74,0.4); border-radius: 6px 6px 0 0;
  padding: 4px 10px; }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  background: rgba(34,211,238,0.15); border-bottom: 2px solid #22d3ee; }
</style>
""", unsafe_allow_html=True)

# --- Oturum durumu ---------------------------------------------------------
ss = st.session_state
ss.setdefault("prev_by_icao", {})
ss.setdefault("model", AnomalyModel(min_train=200))
# Kalici (onceden egitilmis) model varsa yukle — isinma beklemeden olgun tespit
if "pretrained_tried" not in ss:
    ss.pretrained_tried = True
    ss.pretrained_loaded = ss.model.load_pretrained()
ss.setdefault("loop_i", 0)
ss.setdefault("prev_counts", (0, 0, 0))  # onceki tur: uçak, kural, ml (delta icin)
ss.setdefault("quota", QuotaTracker(authenticated=authenticated()))
ss.setdefault("last_fetch", 0.0)          # son gercek istek zamani (unix)
ss.setdefault("cache", None)              # (current, rule_alerts, ml_alerts)
ss.setdefault("tracks", {})               # icao24 -> [[lon,lat],...] rota izi
ss.setdefault("fp", FingerprintStore(min_obs=8))  # uçak parmak izi
ss.setdefault("count_hist", [])           # (uçak, kural, ml) gecmisi = sparkline
ss.setdefault("last_report", "")          # son AI rapor metni
ss.setdefault("auto_offline", False)      # canli veri hata verince cevrimdisi'na dus
ss.setdefault("last_source", "-")         # son veri kaynagi: adsb.lol / opensky / offline

TRACK_LEN = 25  # her uçak icin saklanan son konum sayisi (rota izi)
HIST_LEN = 40   # sparkline nokta sayisi

# --- Kenar cubugu ----------------------------------------------------------
st.sidebar.title("🛰️ ADS-B Guard")

# Canli radar tarama efekti (saf CSS — donen supurme + halkalar + blip)
RADAR_HTML = """
<div class="radar-wrap">
  <div class="radar">
    <div class="ring r1"></div><div class="ring r2"></div><div class="ring r3"></div>
    <div class="cross-h"></div><div class="cross-v"></div>
    <div class="sweep"></div>
    <div class="blip b1"></div><div class="blip b2"></div><div class="blip b3"></div>
  </div>
  <div class="radar-label">● CANLI TARAMA</div>
</div>
<style>
.radar-wrap { display:flex; flex-direction:column; align-items:center; margin:6px 0 12px; }
.radar { position:relative; width:150px; height:150px; border-radius:50%;
  background: radial-gradient(circle, rgba(10,40,30,0.9) 0%, rgba(4,15,12,0.95) 70%);
  border:2px solid #0f6; box-shadow:0 0 14px rgba(0,255,120,0.35), inset 0 0 20px rgba(0,255,120,0.15);
  overflow:hidden; }
.ring { position:absolute; border:1px solid rgba(0,255,120,0.25); border-radius:50%;
  top:50%; left:50%; transform:translate(-50%,-50%); }
.r1{ width:33%; height:33%; } .r2{ width:66%; height:66%; } .r3{ width:96%; height:96%; }
.cross-h,.cross-v { position:absolute; background:rgba(0,255,120,0.2); }
.cross-h { top:50%; left:2%; width:96%; height:1px; }
.cross-v { left:50%; top:2%; height:96%; width:1px; }
.sweep { position:absolute; top:0; left:0; width:100%; height:100%; border-radius:50%;
  background: conic-gradient(from 0deg, rgba(0,255,120,0.45) 0deg, rgba(0,255,120,0.12) 22deg, transparent 55deg, transparent 360deg);
  animation: spin 3s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.blip { position:absolute; width:7px; height:7px; border-radius:50%; background:#5f6;
  box-shadow:0 0 8px #0f6; opacity:0; }
.b1{ top:30%; left:62%; animation: blink 3s linear infinite; }
.b2{ top:64%; left:40%; animation: blink 3s linear infinite 1s; }
.b3{ top:46%; left:70%; animation: blink 3s linear infinite 2s; }
@keyframes blink { 0%{opacity:0;} 10%{opacity:1;} 55%{opacity:0.7;} 100%{opacity:0;} }
.radar-label { margin-top:6px; color:#5f6; font-family:monospace; font-size:12px;
  letter-spacing:1px; text-shadow:0 0 6px rgba(0,255,120,0.5); }
</style>
"""
st.sidebar.markdown(RADAR_HTML, unsafe_allow_html=True)

# BOLGE — en ust, en onemli secim
region = st.sidebar.selectbox("🌍 İzlenen bölge", list(BBOXES.keys()), index=0)
# Otomatik yenile VARSAYILAN KAPALI — sayfa sabit kalir, kullanici zoom/scroll'u
# bozulmaz. Acarsa 30 sn'de bir sessizce gunceller (fragment).
auto = st.sidebar.toggle("🔄 Otomatik yenile (30 sn)", value=False,
                         help="Açıksa 30 sn'de bir veriyi tazeler. KAPALIYSA sayfa "
                              "sabit kalır — aşağıdaki '🔄 Yenile' ile elle güncelle.")

# AYARLAR — expander (varsayilan kapali, arayuz sade)
with st.sidebar.expander("⚙️ Ayarlar", expanded=False):
    use_ml = st.checkbox("ML katmanı", value=True,
                         help="Filo genelinden sıradışı uçakları işaretler. "
                              "Kesin tehdit değil — 'incele' listesi.")
    map_3d = st.checkbox("🗺️ 3D harita (irtifa)", value=False,
                         help="Uçakları irtifaya göre yükseltir.")
    map_zoom = st.slider("🔍 Harita yakınlığı", 1, 9, 5,
                         help="Harita zoom seviyesi — sabit kalır, yenileme bozmaz.")
    sound = st.checkbox("🔊 Sesli alarm", value=False,
                        help="Yüksek-önem alarmda uyarı sesi.")
    st.caption("🔑 Kimlik: **" + ("var (4000/gün)" if authenticated()
                                  else "anonim (~400/gün)") + "**")
    st.caption("🤖 AI rapor: **" + ("Claude aktif" if ai_report.ai_available()
                                    else "şablon") + "**")

# DEMO — expander
with st.sidebar.expander("🎬 Spoof demo modu", expanded=False):
    st.caption("Gerçek trafiğe sahte uçak enjekte et — tespiti canlı gör.")
    offline_mode = st.checkbox(
        "🧪 Çevrimdışı mod (internet yok)", value=False, key="offline_mode",
        help="Açıksa OpenSky'a bağlanmaz; sentetik ama gerçekçi trafik üretir. "
             "Sunum/mülakatta internet olmadan da tespit motoru çalışır.")
    demo_on = st.checkbox("Demo enjeksiyonu aç", value=False)
    scenarios = []
    if demo_on:
        for key, label in SCENARIO_LABELS.items():
            if st.checkbox(label, value=(key in ("teleport", "clone")), key=f"sc_{key}"):
                scenarios.append(key)

st.sidebar.divider()

# --- Kota gostergesi (sidebar — fragment DISINDA, kalici sayactan okur) ----
# Fragment icinden st.sidebar cagirilamaz, o yuzden burada (fragment oncesi)
# kalici QuotaTracker'dan son durumu gosteririz.
_qcost = credit_cost(BBOXES[region])
_qs = ss.quota.status(_qcost)
st.sidebar.markdown("**📊 İstek kotası**")
st.sidebar.progress(min(1.0, _qs["used"] / _qs["budget"]),
                    text=f"{_qs['used']}/{_qs['budget']} kredi")
if _qs["exhausted"]:
    st.sidebar.error(f"Kota bitti — reset ~{_qs['reset_in_min']} dk sonra.")
elif _qs["low"]:
    st.sidebar.warning(f"⚠️ ~{_qs['calls_left']} istek kaldı (kota azalıyor).")
else:
    st.sidebar.caption(f"~{_qs['calls_left']} istek kaldı · {_qcost} kredi/istek")

st.sidebar.divider()
st.sidebar.caption("Veri: OpenSky Network (halka acik). Sadece okuma, savunma amacli.")


def fetch_and_analyze(offline: bool = False):
    bbox = BBOXES[region]
    if offline:
        # Sentetik trafik — ag yok. Demo enjeksiyonu yine ustune biner.
        current = generate_normal_traffic(bbox)
        ss.last_source = "offline"
    else:
        # KAYNAK ZINCIRI: adsb.lol (Cloud'dan erisilebilir, anahtarsiz) ->
        # OpenSky (yerelde iyi, Cloud'da engelli) -> hata ise disarida cevrimdisi.
        try:
            current = adsb_lol.fetch_states(bbox)
            if not current:
                raise RuntimeError("adsb.lol bos dondu")
            ss.last_source = "adsb.lol"
        except Exception:
            current = fetch_states(bbox=bbox)   # OpenSky yedek
            ss.last_source = "opensky"

    # Spoof demo: sahte uçaklari gercek trafige enjekte et (prev'e tohum ekler)
    if demo_on and scenarios:
        if bbox:
            center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        else:
            center = (39.0, 33.0)
        current = current + inject(current, ss.prev_by_icao, scenarios, center)

    rule_alerts = analyze(ss.prev_by_icao, current)

    ml_alerts = []
    if use_ml:
        ss.model.observe(current)
        ss.loop_i += 1
        if ss.loop_i % 5 == 0 or ss.model.model is None:
            ss.model.fit()
        ml_alerts = ss.model.score(current)

    # Fingerprint: her uçagin kendi gecmisi
    ss.fp.observe(current)
    fp_dev = ss.fp.deviations(current)

    # Olaylar: karanlik uçak (onceki prev'e gore) + yakinlasma
    dark = find_dark(ss.prev_by_icao, current, bbox)
    conflicts = find_conflicts(current)
    events = dark + conflicts

    # Geofence ihlalleri
    breaches = check_zones(current)

    # Cok-sinyal dogrulama (verdiktler)
    verdicts = {a.icao24: verify(ss.prev_by_icao.get(a.icao24), a) for a in current}

    # Callsign dogrulama: cagri isareti havayolu-ulke uyumu
    cs_mismatches = []
    for a in current:
        r = validate_callsign(a.callsign, a.country)
        if r["status"] == "mismatch":
            cs_mismatches.append((a.icao24, a.callsign, r["detail"]))

    # Rota sapmasi: uçak bildirdigi yonde mi gidiyor (izinden)
    traj_dev = []
    for a in current:
        pts = ss.tracks.get(a.icao24, [])
        d = trajectory_deviation(pts, a.velocity, a.track)
        if d and d["suspicious"]:
            traj_dev.append((a.icao24, a.callsign or "-", d["deviation_deg"], d["detail"]))

    ss.prev_by_icao = {a.icao24: a for a in current if a.icao24}

    # Rota izi guncelle (sadece gercek yeni veride)
    seen = set()
    for a in current:
        if a.has_position:
            seen.add(a.icao24)
            t = ss.tracks.setdefault(a.icao24, [])
            t.append([a.lon, a.lat])
            if len(t) > TRACK_LEN:
                del t[0]
    # artik gorunmeyen uçaklarin izini birak (bellek sismesin)
    for k in [k for k in ss.tracks if k not in seen]:
        ss.tracks.pop(k, None)

    # Alarm gecmisini diske yaz (kural alarmlari; ML daha yumusak)
    pos = {a.icao24: (a.lat, a.lon) for a in current if a.has_position}
    alerts_db.log_alerts(rule_alerts, pos)

    return {
        "current": current, "rule_alerts": rule_alerts, "ml_alerts": ml_alerts,
        "fp_dev": fp_dev, "events": events, "breaches": breaches,
        "verdicts": verdicts, "cs_mismatches": cs_mismatches, "traj_dev": traj_dev,
    }


# --- Fragment: otomatik yenileme TAM SAYFA RELOAD OLMADAN --------------
# st.fragment(run_every) sadece bu blogu yeniler — sayfa 'gidip gelmez',
# kaydirma korunur, harita zoom'u (sabit view ile) bozulmaz.
_run_every = REFRESH_SECONDS if auto else None

@st.fragment(run_every=_run_every)
def _dashboard():
    # --- Kota-korumali cekme kapisi --------------------------------------------
    bbox = BBOXES[region]
    cost = credit_cost(bbox)
    q: QuotaTracker = ss.quota
    interval = q.next_interval(REFRESH_SECONDS, cost)   # kota azaldikca buyur
    now = time.time()
    age = now - ss.last_fetch

    # Manuel yenile butonu (otomatik kapaliyken elle guncelle)
    manual = st.button("🔄 Yenile", help="Veriyi şimdi tazele.")

    # Kullanici cevrimdisi sectiyse VEYA canli veri daha once patlayip
    # otomatik cevrimdisi'na dustuysek sentetik trafik kullan.
    want_offline = offline_mode or ss.auto_offline

    # Yeni veri: ilk yukleme, manuel buton, VEYA otomatik+sure doldu+kota var.
    # Cevrimdisi modda kota yok — surekli tazele (ag maliyeti sifir).
    should_fetch = (ss.cache is None) or manual or want_offline or (
        auto and age >= interval and q.can_afford(cost))

    if should_fetch:
        try:
            ss.cache = fetch_and_analyze(offline=want_offline)
            if not want_offline:
                # Kota SADECE OpenSky kullanildiysa harcanir (adsb.lol kotasiz).
                if ss.last_source == "opensky":
                    q.record(cost)
                ss.auto_offline = False  # canli veri geldi: fallback kapat
            ss.last_fetch = time.time()
        except Exception as e:
            # Canli veri patladi (Cloud timeout / kota / internet yok).
            # ONEMLI: st.stop() ile OLME — cevrimdisi demoya dus, dashboard yasasin.
            if not want_offline:
                ss.auto_offline = True
                try:
                    ss.cache = fetch_and_analyze(offline=True)
                    ss.last_fetch = time.time()
                except Exception as e2:
                    if ss.cache is None:
                        st.error(f"Veri cekilemedi ve cevrimdisi demo da basarisiz: {e2}")
                        st.stop()
                    st.warning(f"Istek basarisiz, onbellek gosteriliyor: {e}")
            elif ss.cache is None:
                st.error(f"Cevrimdisi demo uretilemedi: {e}")
                st.stop()

    d = ss.cache
    current = d["current"]
    rule_alerts = d["rule_alerts"]
    ml_alerts = d["ml_alerts"]
    fp_dev = d["fp_dev"]
    events = d["events"]
    breaches = d["breaches"]
    verdicts = d["verdicts"]
    cs_mismatches = d.get("cs_mismatches", [])
    traj_dev = d.get("traj_dev", [])
    qs = q.status(cost)

    # --- Cevrimdisi demo afisi -------------------------------------------------
    # Fetch sirasinda auto_offline degismis olabilir — afis AYNI turda ciksin
    # (yoksa bir yenileme geç gorunur).
    want_offline = offline_mode or ss.auto_offline
    if want_offline:
        if offline_mode:
            st.info("🧪 **ÇEVRİMDIŞI DEMO** — sentetik trafik (internet gerekmez). "
                    "Tespit motoru gerçek algoritmalarla çalışıyor. "
                    "Canlı veri için sol menüden çevrimdışı modu kapat.")
        else:
            st.warning("📡 **Canlı veriye ulaşılamadı** (kaynaklar yavaş/engelli olabilir) — "
                       "otomatik **çevrimdışı demoya** geçildi. Motor çalışmaya devam "
                       "ediyor. '🔄 Yenile' ile canlı veriyi tekrar dener.")
    else:
        # Canli — hangi kaynak?
        if ss.last_source == "adsb.lol":
            st.caption("🟢 Canlı veri: **adsb.lol** — gerçek ADS-B (anahtarsız, Cloud uyumlu)")
        elif ss.last_source == "opensky":
            st.caption("🟢 Canlı veri: **OpenSky Network**")

    # --- Kota durumu (ana alan — fragment sidebar'a yazamaz) -------------------
    # NOT: fragment icinde st.sidebar cagrilamaz. Kota durumunu ana alanda goster.
    if want_offline:
        pass  # cevrimdisi: kota harcanmiyor, gosterme
    elif qs["exhausted"]:
        st.error(f"📊 Kota bitti ({qs['used']}/{qs['budget']} kredi). "
                 f"Reset ~{qs['reset_in_min']} dk sonra. İstek durdu, veri önbellekten.")
    elif qs["low"]:
        st.warning(f"📊 Kota az ({qs['used']}/{qs['budget']} kredi, ~{qs['calls_left']} "
                   f"istek). Aralık otomatik **{int(interval)} s**'ye uzatıldı.")
    else:
        st.caption(f"📊 Kota: {qs['used']}/{qs['budget']} kredi · ~{qs['calls_left']} "
                   f"istek kaldı · aralık {int(interval)} s · {cost} kredi/istek")

    high_icao = {a.icao24 for a in rule_alerts if a.severity == "high"}
    warn_icao = {a.icao24 for a in rule_alerts if a.severity in ("med", "low")}
    ml_icao = {a.icao24 for a in ml_alerts}

    # --- DURUM OZETI (tek bakista tehdit seviyesi) -----------------------------
    # Onceliklendirme: kanitlanmis > yuksek kural > olay/geofence > ML/sube
    n_high = len([a for a in rule_alerts if a.severity == "high"])
    n_breach = len(breaches)
    n_cs = len(cs_mismatches)
    n_dark = len([e for e in events if e.kind == "dark"])
    n_ml = len(ml_alerts)
    n_traj = len(traj_dev)
    if n_high or n_breach:
        st.error(f"🔴 **DİKKAT** — {n_high} imkansız hareket, {n_breach} yasak-bölge "
                 "ihlali. Fiziksel/mantıksal imkansız = güçlü spoofing / gerçek "
                 "tehdit sinyali. Detay için aşağıdaki sekmelere bak.")
    elif n_dark or n_ml or n_traj or n_cs:
        st.warning(f"🟡 **İZLE** — {n_dark} kayıp sinyal, {n_ml} sıradışı uçak, "
                   f"{n_cs} çağrı-ülke uyuşmazlığı, {n_traj} rota sapması. Kesin "
                   "tehdit değil (çapraz-tescil normal olabilir), göz at.")
    else:
        st.success("🟢 **SAKİN** — trafik temiz, yüksek-önem tehdit yok.")

    # --- Ust metrikler (basit, anlasilir) --------------------------------------
    p_ac, p_rule, p_ml = ss.prev_counts
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("✈️ Uçak", len(current), delta=len(current) - p_ac)
    c2.metric("🔴 Kesin alarm", n_high + n_breach,
              delta=(n_high + n_breach) - p_rule, delta_color="inverse",
              help="İmkansız hareket + yasak bölge (fiziksel imkansız)")
    c3.metric("🟡 İncele", n_ml + n_dark + n_traj + n_cs, delta=n_ml - p_ml,
              delta_color="inverse",
              help="Sıradışı + kayıp sinyal + rota sapması + çağrı-ülke uyuşmazlığı")
    c4.metric("🎯 MLAT/ML", "hazır" if ss.model.trained else "ısınıyor",
              help=f"ML backend: {ss.model.backend}")
    ss.prev_counts = (len(current), n_high + n_breach, len(ml_alerts))

    # Sparkline: uçak + alarm zaman-serisi (canli istatistik seridi)
    ss.count_hist.append({"uçak": len(current), "kural": len(rule_alerts),
                          "ml": len(ml_alerts)})
    if len(ss.count_hist) > HIST_LEN:
        del ss.count_hist[0]
    if len(ss.count_hist) >= 3:
        sp1, sp2 = st.columns(2)
        hist = pd.DataFrame(ss.count_hist)
        sp1.caption("Uçak sayısı trendi")
        sp1.line_chart(hist[["uçak"]], height=90)
        sp2.caption("Alarm trendi (kural + ML)")
        sp2.line_chart(hist[["kural", "ml"]], height=90)

    # Sesli alarm: yuksek-onem alarm varsa kisa beep (tarayici, gizli audio)
    high_now = [a for a in rule_alerts if a.severity == "high"]
    if sound and high_now:
        st.markdown("""
        <audio autoplay><source src="data:audio/wav;base64,UklGRl9vT19XQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=" type="audio/wav"></audio>
        <script>
        (function(){try{var c=new (window.AudioContext||window.webkitAudioContext)();
        var o=c.createOscillator();var g=c.createGain();o.connect(g);g.connect(c.destination);
        o.type='square';o.frequency.value=880;g.gain.value=0.06;o.start();
        o.stop(c.currentTime+0.25);}catch(e){}})();
        </script>""", unsafe_allow_html=True)

    # --- Harita verisi ---------------------------------------------------------
    emergency = [a for a in rule_alerts if a.kind == "emergency_squawk"]

    rows = []
    for ac in current:
        if not ac.has_position:
            continue
        high = ac.icao24 in high_icao
        warn = ac.icao24 in warn_icao
        ml = ac.icao24 in ml_icao
        if high:
            color, kind, tri_m = [235, 45, 45], "Kural alarmı (yüksek)", 5000
        elif ml:
            color, kind, tri_m = [200, 70, 225], "ML aykırı", 4500
        elif warn:
            color, kind, tri_m = [240, 175, 45], "Kural uyarı", 4500
        else:
            color, kind, tri_m = [90, 190, 235], "Normal", 3000
        track = ac.track if ac.track is not None else 0.0
        ts = trust_score(ac, high, warn, ml)
        mil = is_military(ac.icao24)
        v = verdicts.get(ac.icao24)
        rows.append({
            "icao24": ac.icao24, "callsign": ac.callsign or "-",
            "lat": ac.lat, "lon": ac.lon,
            "alt": round(ac.baro_alt or 0), "vel": round(ac.velocity or 0),
            "durum": kind, "color": color,
            "guven": ts, "guven_lbl": trust_label(ts),
            "askeri": "🎖️ askeri" if mil else "sivil",
            "kaynak": source_label(ac),
            "squawk": ac.squawk or "-",
            "ulke": ac.country,
            "dogrulama": VERDICT_LABEL.get(v.status, "-") if v else "-",
            "dogrulama_skor": v.confidence if v else 100,
            "elev": float(ac.baro_alt or 0),   # 3D yukseklik
            "poly": plane_triangle(ac.lat, ac.lon, track, tri_m),
        })
    df = pd.DataFrame(rows)

    # Rota izi katmani verisi: >=2 noktali izler, durum rengiyle
    track_rows = []
    for icao, pts in ss.tracks.items():
        if len(pts) >= 2:
            tc = [235, 45, 45] if icao in high_icao else (
                [200, 70, 225] if icao in ml_icao else [130, 150, 170])
            track_rows.append({"path": list(pts), "color": tc})
    track_df = pd.DataFrame(track_rows)

    # Acil durum + askeri ozet satiri
    mil_count = int((df["askeri"] == "🎖️ askeri").sum()) if not df.empty else 0
    if emergency:
        for a in emergency:
            st.error(f"🚨 ACİL DURUM — {a.callsign or a.icao24}: {a.detail}")
    st.caption(f"🎖️ Askeri (tahmini): **{mil_count}**   ·   "
               f"🚨 Acil durum kodu: **{len(emergency)}**   ·   "
               f"📈 Son 24s alarm: **{alerts_db.recent_count(24)}**")

    (tab_traffic, tab_events, tab_jam, tab_mlat, tab_hist, tab_ai,
     tab_sea) = st.tabs(
        ["🛩️ Trafik", "⚠️ Olaylar", "📡 GPS Jamming", "🎯 MLAT",
         "📈 Alarm geçmişi", "🤖 AI Rapor", "🚢 Deniz (AIS)"])

    # --- SEKME 1: canli trafik + alarmlar --------------------------------------
    with tab_traffic:
        st.subheader("Canlı trafik haritası")

        # Arama + filtre (kullanislilik)
        fc1, fc2 = st.columns([2, 1])
        search = fc1.text_input("🔍 Uçak ara (çağrı/ICAO)", "",
                                placeholder="örn: THY, PGT, 4bc8...").strip().lower()
        only_alerts = fc2.checkbox("⚠️ Sadece alarmlı uçaklar", value=False)

        map_df = df
        if not df.empty:
            if search:
                map_df = map_df[map_df["callsign"].str.lower().str.contains(search, na=False)
                                | map_df["icao24"].str.lower().str.contains(search, na=False)]
            if only_alerts:
                alerted = high_icao | warn_icao | ml_icao
                map_df = map_df[map_df["icao24"].isin(alerted)]
            if search or only_alerts:
                st.caption(f"Filtre: {len(map_df)}/{len(df)} uçak gösteriliyor.")
            # CSV disa aktar (anlik trafik)
            csv = df[["icao24", "callsign", "lat", "lon", "alt", "vel", "durum",
                      "guven", "askeri", "kaynak", "ulke"]].to_csv(index=False)
            st.download_button("⬇️ Trafiği CSV indir", data=csv,
                               file_name="adsb_trafik.csv", mime="text/csv")

        if not map_df.empty:
            df_show = map_df
            # SABIT bolge merkezi + kullanici zoom (slider). df.mean() DEGIL —
            # uçaklar hareket etse/yenilense de harita kaymaz, zoom korunur.
            _vlat, _vlon, _ = MAP_VIEW[region]
            view = pdk.ViewState(
                latitude=_vlat, longitude=_vlon, zoom=map_zoom,
                pitch=50 if map_3d else 0,
            )
            layers = []
            # En alt: rota izi (uçagin gectigi yol). Spoof izi zigzag/kopuk olur.
            if not track_df.empty:
                layers.append(pdk.Layer(
                    "PathLayer", data=track_df,
                    get_path="path", get_color="color",
                    width_min_pixels=1, opacity=0.5,
                ))
            if map_3d:
                # 3D: uçaklari irtifaya gore yukselt (ColumnLayer sütun)
                layers.append(pdk.Layer(
                    "ColumnLayer", data=df_show,
                    get_position="[lon, lat]", get_elevation="elev",
                    elevation_scale=6, radius=1500,
                    get_fill_color="color", pickable=True, opacity=0.85,
                ))
            else:
                # 2D: nokta + yon ucgeni
                layers.append(pdk.Layer(
                    "ScatterplotLayer", data=df_show,
                    get_position="[lon, lat]", get_fill_color="color",
                    get_radius=1500, radius_min_pixels=1.5, radius_max_pixels=3,
                    opacity=0.8, pickable=True,
                ))
                layers.append(pdk.Layer(
                    "PolygonLayer", data=df_show,
                    get_polygon="poly", get_fill_color="color",
                    get_line_color=[255, 255, 255, 140], line_width_min_pixels=1,
                    stroked=True, filled=True, pickable=True,
                ))
            st.pydeck_chart(pdk.Deck(
                layers=layers, initial_view_state=view, map_style="dark",
                tooltip={"text": "{callsign} ({icao24})  {askeri}\n{durum}  ·  güven {guven}/100\n"
                                 "irtifa {alt} m  hız {vel} m/s  ·  {dogrulama}"},
            ))
            st.caption("✈️ renk = durum:  🔴 kural-yüksek   🟠 kural-uyarı   "
                       "🟣 ML-aykırı   🔵 normal   ·   burun = uçuş yönü   ·   "
                       "çizgi = rota izi")
        elif df.empty:
            st.info("Konumlu uçak yok.")
        else:
            st.info("Filtreye uyan uçak yok — aramayı temizle veya değiştir.")

        st.subheader("Kural alarmları — fiziksel/mantıksal imkansızlıklar")
        st.caption("Bunlar bilinen spoofing izleri. Fiziksel olarak olamayacak hareketler.")
        if rule_alerts:
            ra = sorted(rule_alerts, key=lambda a: SEV_RANK.get(a.severity, 9))
            st.dataframe(pd.DataFrame([{
                "Önem": SEV_LABEL.get(a.severity, a.severity),
                "Uçak (ICAO)": a.icao24,
                "Çağrı": a.callsign or "-",
                "Sorun": KIND_LABELS.get(a.kind, a.kind),
                "Açıklama": a.detail,
            } for a in ra]), width="stretch", hide_index=True)
        else:
            st.success("Kural alarmı yok — trafik temiz görünüyor.")

        st.subheader("İstatistiksel aykırılar — filo genelinden sıradışı")
        st.caption("⚠️ Bunlar **tehdit değil** — sadece filo geneline göre en sıradışı "
                   "uçaklar (mutlak eşik, temiz trafikte ~%0.5). Askeri jet, özel uçak, "
                   "sıradışı irtifa/hız da buraya düşebilir. 'İncele' listesidir, alarm değil.")
        if ml_alerts:
            st.dataframe(pd.DataFrame([{
                "Uçak (ICAO)": a.icao24,
                "Çağrı": a.callsign or "-",
                "Aykırılık skoru": round(a.score, 3),
                "Açıklama": a.detail,
            } for a in sorted(ml_alerts, key=lambda x: x.score)]),
                width="stretch", hide_index=True)
        else:
            st.info("ML alarmı yok / model henüz ısınıyor.")

        # En düşük güven skorlu uçaklar = spoofing şüphelileri
        st.subheader("En düşük güven — spoofing şüphelileri")
        st.caption("Güven skoru: 100 = temiz/tutarlı, düşük = veri şüpheli. "
                   "Alarm + zayıf sinyalden hesaplanır. MLAT (bağımsız doğrulama) yükseltir.")
        if not df.empty:
            low = df[df["guven"] < 100].sort_values("guven").head(15)
            if not low.empty:
                st.dataframe(pd.DataFrame({
                    "Güven": low["guven"].astype(str) + "/100",
                    "Durum": low["guven_lbl"],
                    "Uçak (ICAO)": low["icao24"],
                    "Çağrı": low["callsign"],
                    "Askeri": low["askeri"],
                    "Kaynak": low["kaynak"],
                    "Ülke": low["ulke"],
                }), width="stretch", hide_index=True)
            else:
                st.success("Tüm uçaklar tam güven (100/100) — trafik temiz.")

        # Uçak detay paneli
        st.subheader("Uçak detayı")
        if not df.empty:
            opts = {f"{r.callsign}  ({r.icao24})": r.icao24 for r in df.itertuples()}
            pick = st.selectbox("Uçak seç", list(opts.keys()), index=0)
            sel = df[df["icao24"] == opts[pick]].iloc[0]
            d1, d2, d3 = st.columns(3)
            d1.metric("Güven", f"{sel['guven']}/100", help=sel["guven_lbl"])
            d2.metric("İrtifa", f"{sel['alt']} m")
            d3.metric("Hız", f"{sel['vel']} m/s")
            st.write({
                "ICAO24": sel["icao24"], "Çağrı": sel["callsign"],
                "Ülke": sel["ulke"], "Durum": sel["durum"],
                "Doğrulama": f"{sel['dogrulama']} ({sel['dogrulama_skor']}/100)",
                "Askeri": sel["askeri"], "Konum kaynağı": sel["kaynak"],
                "Squawk": sel["squawk"],
                "Rota izi nokta sayısı": len(ss.tracks.get(sel["icao24"], [])),
                "Konum": f"{sel['lat']:.4f}, {sel['lon']:.4f}",
            })
            # Cok-sinyal dogrulama gerekceleri
            vv = verdicts.get(sel["icao24"])
            if vv and vv.reasons:
                st.caption("**Doğrulama kanıtları:**  " + "  ·  ".join(vv.reasons))
            # Uçak tipi/tescil (hexdb.io — buton ile, her uçak icin API cagirmamak icin)
            if st.button("🔎 Uçak tipi/tescil sorgula (hexdb.io)"):
                info = aircraft_type(sel["icao24"])
                if info and any(info.values()):
                    st.write({k: v for k, v in {
                        "Tescil": info.get("registration"),
                        "Tip": info.get("type"),
                        "Üretici": info.get("manufacturer"),
                        "İşletmeci": info.get("operator"),
                    }.items() if v})
                else:
                    st.info("Bu uçak veritabanında bulunamadı.")

    # --- SEKME: Olaylar (karanlik uçak, cakisma, geofence, fingerprint) --------
    with tab_events:
        st.subheader("Olaylar ve ihlaller")

        dark = [e for e in events if e.kind == "dark"]
        conflicts = [e for e in events if e.kind == "conflict"]

        st.markdown("**📛 Çağrı işareti uyuşmazlığı — sahte kimlik şüphesi**")
        st.caption("Çağrı işareti havayolu kodu ile uçağın bildirdiği ülke "
                   "uyuşmuyor (örn. THY=Türk ama uçak Almanya diyor). Spoofer "
                   "rastgele çağrı uydurmuş olabilir.")
        if cs_mismatches:
            st.dataframe(pd.DataFrame([{
                "Uçak": m[0], "Çağrı": m[1], "Uyuşmazlık": m[2]}
                for m in cs_mismatches]), width="stretch", hide_index=True)
        else:
            st.success("Çağrı işareti uyuşmazlığı yok.")

        st.markdown("**🧭 Rota sapması — bildirilen yönden farklı gidiyor**")
        st.caption("Uçağın gerçek gidiş yönü, bildirdiği yön (track) ile >45° "
                   "sapıyor. Manevra veya spoof izi olabilir.")
        if traj_dev:
            st.dataframe(pd.DataFrame([{
                "Uçak": t[0], "Çağrı": t[1], "Sapma°": t[2], "Açıklama": t[3]}
                for t in traj_dev]), width="stretch", hide_index=True)
        else:
            st.success("Rota sapması yok.")

        st.markdown("**🕳️ Karanlık uçaklar — sinyal aniden kesildi**")
        st.caption("Seyir irtifasında olup bu turda kaybolan uçak. Transponder "
                   "kapatma = kaçış/gizlenme işareti olabilir.")
        if dark:
            st.dataframe(pd.DataFrame([{
                "Uçak": e.icao24, "Açıklama": e.detail} for e in dark]),
                width="stretch", hide_index=True)
        else:
            st.success("Karanlık uçak yok.")

        st.markdown("**🔀 Tehlikeli yakınlaşmalar (TCAS-benzeri)**")
        st.caption("İki uçak yatay <5 nm ve dikey <300 m. Çakışma riski göstergesi.")
        if conflicts:
            st.dataframe(pd.DataFrame([{
                "Açıklama": e.detail} for e in conflicts]),
                width="stretch", hide_index=True)
        else:
            st.success("Tehlikeli yakınlaşma yok.")

        st.markdown("**🛑 Coğrafi-çit ihlalleri (havaalanı / yasak bölge)**")
        st.caption(f"{len(DEFAULT_ZONES)} tanımlı bölge izleniyor.")
        if breaches:
            st.dataframe(pd.DataFrame([{
                "Bölge": b.zone, "Tür": b.kind, "Uçak": b.icao24,
                "Çağrı": b.callsign, "Mesafe (km)": b.dist_km,
                "İrtifa (m)": round(b.alt) if b.alt else "-",
            } for b in breaches]), width="stretch", hide_index=True)
        else:
            st.success("Bölge ihlali yok.")

        st.markdown("**🧬 Parmak izi sapması — uçak kendi normalinden saptı**")
        st.caption("Genel ML tüm filoya bakar; fingerprint TEK uçağın kendi "
                   "geçmişine bakar. Zamanla dolar (uçak başına ≥8 gözlem gerekir).")
        if fp_dev:
            st.dataframe(pd.DataFrame([{
                "Uçak": d0[0], "Çağrı": d0[1], "Alan": d0[2], "Sapma (σ)": d0[3],
            } for d0 in fp_dev]), width="stretch", hide_index=True)
        else:
            st.info("Fingerprint sapması yok / profiller henüz ısınıyor.")

    # --- SEKME 2: GPS jamming isi haritasi -------------------------------------
    with tab_jam:
        st.subheader("GPS jamming şüpheli bölgeler")
        st.caption("Vekil gösterge: barometrik (GPS'siz) vs geometrik (GPS) irtifa "
                   "sapması >1200 m ya da GNSS irtifası hiç yok. Kesin kanıt değil, "
                   "şüphe haritası. Avrupa/Tüm dünya daha çok veri görür.")
        cells = build_grid(current, cell_deg=1.0)
        zones = suspected_zones(cells, min_total=3, min_ratio=0.5)

        hot = [c for c in cells if c.total >= 3 and c.ratio > 0]
        if hot:
            hdf = pd.DataFrame([{
                "lat": c.lat, "lon": c.lon, "ratio": c.ratio,
                "total": c.total, "degraded": c.degraded,
                "color": [int(60 + 195 * c.ratio), int(60 * (1 - c.ratio)), 40],
                "weight": c.ratio,
            } for c in hot])
            view = pdk.ViewState(latitude=hdf["lat"].mean(),
                                 longitude=hdf["lon"].mean(),
                                 zoom=2 if region == "Tum dunya" else 4)
            heat = pdk.Layer(
                "HeatmapLayer", data=hdf,
                get_position="[lon, lat]", get_weight="weight",
                radius_pixels=40, opacity=0.6,
            )
            grid = pdk.Layer(
                "ScatterplotLayer", data=hdf,
                get_position="[lon, lat]", get_fill_color="color",
                get_radius=25000, pickable=True, opacity=0.5,
            )
            st.pydeck_chart(pdk.Deck(
                layers=[heat, grid], initial_view_state=view, map_style="dark",
                tooltip={"text": "bozulma {degraded}/{total} uçak"},
            ))
        else:
            st.info("Bu bölgede değerlendirilebilir seyir trafiği yok.")

        if zones:
            st.warning(f"{len(zones)} yüksek-şüpheli bölge:")
            st.dataframe(pd.DataFrame([{
                "Enlem": round(z.lat, 1), "Boylam": round(z.lon, 1),
                "Bozulma oranı": f"{z.ratio*100:.0f}%",
                "Bozulmuş": z.degraded, "Toplam uçak": z.total,
            } for z in zones]), width="stretch", hide_index=True)
        else:
            st.success("Yüksek-şüpheli jamming bölgesi yok.")

    # --- SEKME: Multilateration (MLAT) -----------------------------------------
    with tab_mlat:
        st.subheader("🎯 Multilateration — bağımsız konum doğrulama")
        st.markdown(
            "Gerçek MLAT için **birden fazla yer alıcısının** aynı sinyali duyduğu "
            "**ham zaman-damgaları** gerekir (kendi RTL-SDR ağın veya OpenSky Impala "
            "akademik erişim). Bu, spoofing'i **şüphe**'den **kanıt**'a çevirir: "
            "uçak yalan konum yayınlıyorsa bağımsız üçgenleme onu başka yerde bulur.")

        if not _HAS_NUMPY:
            st.error("numpy gerekli — MLAT çözücü çalışamıyor.")
        else:
            st.markdown("**🧪 Canlı demo — TDOA çözücüyü çalıştır**")
            st.caption("Bilinen bir uçak konumu seç. Sistem 6 yer alıcısının duyacağı "
                       "zamanları hesaplar (gerçekçi gürültüyle), sonra SADECE zamanlardan "
                       "konumu geri çözer. Bu gerçek multilateration matematiği.")

            mc1, mc2, mc3 = st.columns(3)
            d_lat = mc1.number_input("Uçak enlem", 35.0, 43.0, 39.5, 0.1)
            d_lon = mc2.number_input("Uçak boylam", 25.0, 45.0, 32.5, 0.1)
            d_alt = mc3.number_input("İrtifa (m)", 1000, 12000, 10000, 500)
            noise_ns = st.slider("Alıcı saat gürültüsü (ns)", 0, 500, 100, 10,
                                 help="Gerçek alıcılar ~50-200ns hata yapar.")

            if st.button("🎯 MLAT çöz"):
                # Bilinen emitter -> alici varis zamanlari (gurultuyle)
                ex, ey, ez = geodetic_to_ecef(d_lat, d_lon, d_alt)
                stations = [(41.0, 29.0, 100), (40.0, 33.0, 900), (38.0, 27.0, 50),
                            (37.0, 35.0, 1000), (39.0, 30.0, 800), (42.0, 31.0, 600)]
                _rnd.seed()
                rxs = []
                for la, lo, al in stations:
                    sx, sy, sz = geodetic_to_ecef(la, lo, al)
                    t = _m.sqrt((ex - sx) ** 2 + (ey - sy) ** 2 + (ez - sz) ** 2) / C
                    t += _rnd.gauss(0, noise_ns * 1e-9)
                    rxs.append(Receiver(la, lo, al, t))

                res = solve_tdoa(rxs, alt_hint=d_alt)
                if res and res.converged:
                    err_m = _m.sqrt((res.lat - d_lat) ** 2 +
                                    (res.lon - d_lon) ** 2) * 111000
                    r1, r2, r3 = st.columns(3)
                    r1.metric("Gerçek konum", f"{d_lat:.3f}, {d_lon:.3f}")
                    r2.metric("MLAT çözümü", f"{res.lat:.3f}, {res.lon:.3f}")
                    r3.metric("Konum hatası", f"{err_m:.0f} m",
                              help=f"kalıntı {res.residual_m:.1f} m")
                    st.success(f"✅ {res.receivers_used} alıcının SADECE zaman "
                               f"farklarından konum {err_m:.0f} m hatayla çözüldü. "
                               "Gerçek TDOA multilateration.")

                    # Harita: alicilar + gercek + MLAT konumu
                    mdf = pd.DataFrame(
                        [{"lat": la, "lon": lo, "tip": "alıcı", "color": [90, 190, 235]}
                         for la, lo, _ in stations]
                        + [{"lat": d_lat, "lon": d_lon, "tip": "gerçek",
                            "color": [90, 235, 120]},
                           {"lat": res.lat, "lon": res.lon, "tip": "MLAT",
                            "color": [235, 200, 45]}])
                    st.pydeck_chart(pdk.Deck(
                        layers=[pdk.Layer("ScatterplotLayer", data=mdf,
                                get_position="[lon, lat]", get_fill_color="color",
                                get_radius=15000, opacity=0.7, pickable=True)],
                        initial_view_state=pdk.ViewState(latitude=d_lat, longitude=d_lon,
                                                         zoom=5),
                        map_style="dark",
                        tooltip={"text": "{tip}"}))
                    st.caption("🔵 alıcılar   🟢 gerçek konum   🟡 MLAT çözümü")
                else:
                    st.error("Çözüm yakınsamadı (alıcı geometrisi zayıf olabilir).")

            st.divider()
            st.markdown("**🛰️ Canlı çapraz-kontrol — OpenSky'ın MLAT verisi**")
            st.caption("OpenSky bazı uçakları zaten MLAT ile konumlandırmış "
                       "(kaynak = MLAT). Bu uçaklar için OpenSky bağımsız üçgenleme "
                       "yapmış demektir. Aşağıda MLAT-kaynaklı uçaklar listeli.")
            mlat_ac = [ac for ac in current if ac.position_source == 2 and ac.has_position]
            if mlat_ac:
                st.dataframe(pd.DataFrame([{
                    "ICAO24": ac.icao24, "Çağrı": ac.callsign or "-",
                    "Enlem": round(ac.lat, 3), "Boylam": round(ac.lon, 3),
                    "İrtifa": round(ac.baro_alt or 0),
                } for ac in mlat_ac]), width="stretch", hide_index=True)
            else:
                st.info("Bu bölgede MLAT-kaynaklı uçak yok (çoğu uçak ADS-B kullanır; "
                        "MLAT genelde ADS-B'siz eski uçaklarda görülür).")

    # --- SEKME 3: alarm gecmisi (SQLite) ---------------------------------------
    with tab_hist:
        st.subheader("Alarm geçmişi")
        st.caption("Tüm kural alarmları diske (alerts.db) kaydedilir. "
                   "Oturumlar arası kalıcıdır.")
        h1, h2 = st.columns(2)
        h1.metric("Son 24 saat alarm", alerts_db.recent_count(24))
        h2.metric("Son 1 saat alarm", alerts_db.recent_count(1))

        st.markdown("**Saatlik alarm trendi (son 24s)**")
        hc = alerts_db.hourly_counts(24)
        trend = pd.DataFrame(hc, columns=["saat", "alarm"]).set_index("saat")
        st.bar_chart(trend, height=200)

        st.markdown("**En çok alarm üreten uçaklar (son 24s)**")
        top = alerts_db.top_offenders(24, limit=10)
        if top:
            st.dataframe(pd.DataFrame(top, columns=["ICAO24", "Çağrı", "Alarm sayısı"]),
                         width="stretch", hide_index=True)
        else:
            st.info("Henüz kayıtlı alarm yok.")

        # Zaman makinesi: gecmis alarmlari harita uzerinde geri-oynat
        st.divider()
        st.markdown("**⏮️ Zaman makinesi — geçmiş alarmları haritada gör**")
        st.caption("Kaydırıcıyla geçmişte bir pencere seç; o aralıkta nerede alarm "
                   "olduğunu haritada göster.")
        win = st.slider("Kaç saat öncesi? (pencere: seçilen saat ± 0.5s)",
                        0.5, 24.0, 1.0, 0.5)
        past = alerts_db.alerts_in_window(win + 0.5, max(0.0, win - 0.5))
        if past:
            pdf2 = pd.DataFrame(past, columns=["ts", "icao24", "callsign", "kind",
                                               "severity", "lat", "lon"])
            pdf2["color"] = pdf2["severity"].map(
                lambda s: [235, 45, 45] if s == "high" else [240, 175, 45])
            st.caption(f"{len(pdf2)} alarm bulundu.")
            st.pydeck_chart(pdk.Deck(
                layers=[pdk.Layer("ScatterplotLayer", data=pdf2,
                                  get_position="[lon, lat]", get_fill_color="color",
                                  get_radius=12000, opacity=0.6, pickable=True)],
                initial_view_state=pdk.ViewState(
                    latitude=pdf2["lat"].mean(), longitude=pdf2["lon"].mean(), zoom=3),
                map_style="dark",
                tooltip={"text": "{callsign} ({icao24})\n{kind} — {severity}"}))
        else:
            st.info("Bu pencerede kayıtlı konumlu alarm yok "
                    "(sistemi bir süre çalıştır, geçmiş birikir).")

    # --- SEKME: AI tehdit raporu -----------------------------------------------
    with tab_ai:
        st.subheader("🤖 AI tehdit raporu")
        if ai_report.ai_available():
            st.caption("Claude Opus 5 canlı tespit çıktısını doğal dil Türkçe "
                       "tehdit raporuna çevirir.")
        else:
            st.caption("ANTHROPIC_API_KEY ayarlı değil — şablon raporu gösteriliyor. "
                       "Anahtar eklersen Claude ayrıntılı analiz yazar.")
        zones_now = suspected_zones(build_grid(current))
        if st.button("📝 Rapor üret"):
            with st.spinner("Rapor hazırlanıyor..."):
                ss.last_report = ai_report.generate_report(
                    current, rule_alerts, ml_alerts, zones_now, events, breaches, region)
        if ss.last_report:
            st.markdown(ss.last_report)
        else:
            st.info("Rapor üretmek için butona bas.")

        st.divider()
        st.markdown("**📄 Dışa aktarma & bildirim**")
        col_a, col_b = st.columns(2)

        # PDF/HTML rapor indir
        html_doc = None
        try:
            # HTML string uret (dosya yerine bellekte)
            import tempfile, os as _os
            tmp = _os.path.join(tempfile.gettempdir(), "adsb_rapor.html")
            build_html_report(current, rule_alerts, ml_alerts, zones_now, region, tmp)
            with open(tmp, encoding="utf-8") as f:
                html_doc = f.read()
        except Exception as e:
            col_a.caption(f"Rapor üretilemedi: {e}")
        if html_doc:
            col_a.download_button("📄 HTML rapor indir (Ctrl+P → PDF)",
                                  data=html_doc, file_name="adsb_rapor.html",
                                  mime="text/html")

        # Telegram/Discord bildirim
        ch = notify.configured()
        if ch["telegram"] or ch["discord"]:
            if col_b.button("📤 Yüksek alarmları bildir"):
                res = notify.notify_high_alerts(rule_alerts, region)
                col_b.write(res if res else "Yüksek-önem alarm yok, gönderilmedi.")
        else:
            col_b.caption("📤 Telegram/Discord ayarlı değil "
                          "(TELEGRAM_BOT_TOKEN / DISCORD_WEBHOOK_URL).")

    # --- SEKME: Deniz (AIS) — CANLI gemi trafigi + spoofing tespiti -----------
    with tab_sea:
        st.subheader("🚢 Deniz trafiği (AIS)")
        st.caption("Gemiler de AIS ile **şifresiz** konum yayınlar — uçaklarla "
                   "aynı spoofing sorunu. İmkansız hız, klon MMSI tespit edilir.")

        SEA_BOXES = {
            "İstanbul Boğazı + Marmara": (40.3, 26.5, 41.3, 29.9),
            "Ege (İzmir-Çanakkale)": (37.5, 25.0, 40.3, 27.5),
            "Akdeniz (Antalya-Mersin)": (35.5, 29.0, 37.0, 35.0),
            "Karadeniz kıyısı": (41.0, 28.0, 42.5, 40.0),
        }

        def _render_ships(ships, prev, view_zoom=7):
            """Gemi haritasi + tespit + alarm tablosu (demo/canli ortak)."""
            sea_alerts = analyze_ships(prev, ships)
            m1, m2 = st.columns(2)
            m1.metric("🚢 Gemi", len(ships))
            m2.metric("⚠️ Gemi alarmı", len(sea_alerts))
            alert_mmsi = {a.mmsi for a in sea_alerts}
            sdf = pd.DataFrame([{
                "lat": s.lat, "lon": s.lon, "mmsi": s.mmsi,
                "name": s.name or "-", "sog": round(s.sog or 0, 1),
                "color": [235, 45, 45] if s.mmsi in alert_mmsi else [40, 200, 180]}
                for s in ships if s.has_position])
            if not sdf.empty:
                st.pydeck_chart(pdk.Deck(
                    layers=[pdk.Layer("ScatterplotLayer", data=sdf,
                            get_position="[lon, lat]", get_fill_color="color",
                            get_radius=2000, radius_min_pixels=3, opacity=0.8,
                            pickable=True)],
                    initial_view_state=pdk.ViewState(
                        latitude=sdf["lat"].mean(), longitude=sdf["lon"].mean(),
                        zoom=view_zoom),
                    map_style="dark",
                    tooltip={"text": "{name} ({mmsi})\nhız {sog} knot"}))
                st.caption("🔵 normal gemi   🔴 alarmlı gemi (klon MMSI / imkansız hız)")
            if sea_alerts:
                st.error(f"🔴 {len(sea_alerts)} gemi alarmı — spoofing şüphesi:")
                st.dataframe(pd.DataFrame([{
                    "MMSI": a.mmsi, "Gemi": a.name, "Tür": a.kind,
                    "Açıklama": a.detail} for a in sea_alerts]),
                    width="stretch", hide_index=True)
            else:
                st.success("Gemi trafiği temiz — spoofing yok.")

        # Demo VARSAYILAN: anahtar yoksa acik; anahtar varsa kullanici acabilir.
        # aisstream ucretsiz katmani kararsiz — demo her zaman calisir.
        demo_ships_on = st.checkbox(
            "🧪 Demo gemi trafiği (anahtarsız — hareketli gemiler + spoofing)",
            value=not ais_available(), key="demo_ships",
            help="aisstream anahtarı gerekmez. Sentetik hareketli gemiler üretir, "
                 "içine klon MMSI + imkansız hız spoof gömer — tespit motorunu "
                 "canlı gösterir.")

        if demo_ships_on:
            from ais import generate_demo_ships
            sea_region = st.selectbox("Deniz bölgesi", list(SEA_BOXES.keys()),
                                      key="demo_sea_region")
            ships, prev = generate_demo_ships(SEA_BOXES[sea_region])
            st.info("🧪 Çevrimdışı demo — gerçek AIS algoritması, sentetik gemiler. "
                    "'🔄 Yenile' ile gemiler ilerler.")
            _render_ships(ships, prev)
        elif not ais_available():
            st.warning("⚓ Canlı gemi için **aisstream.io anahtarı** gerekir "
                       "([aisstream.io](https://aisstream.io) → kayıt → anahtar → "
                       "secrets'a `AISSTREAM_KEY`). Ya da yukarıdaki **demo**yu aç.")
        else:
            st.success("⚓ Canlı AIS anahtarı bağlı.")
            sea_region = st.selectbox("Deniz bölgesi", list(SEA_BOXES.keys()))
            sea_secs = st.slider("Dinleme süresi (sn)", 5, 30, 15,
                                 help="Uzun süre = daha çok gemi ama daha yavaş.")
            if st.button("🚢 Canlı gemileri çek"):
                with st.spinner(f"Gemi verisi çekiliyor (~{sea_secs} sn)..."):
                    from ais import fetch_ships_debug
                    prev_ships = {s.mmsi: s for s in ss.get("ships_cache", [])}
                    ships, sea_status = fetch_ships_debug(SEA_BOXES[sea_region],
                                                          seconds=sea_secs)
                    ss.ships_cache = ships
                    ss.ships_prev = prev_ships
                    ss.sea_status = sea_status

            if ss.get("sea_status"):
                s = ss.sea_status
                if "OK:" in s:
                    st.success(s)
                elif "HATA" in s or "geçersiz" in s:
                    st.error(s + "  → Anahtarı kontrol et veya yukarıdan **demo**yu aç.")
                else:
                    st.info(s + "  → Boğaz'da veri gelmezse anahtar geçersiz olabilir; "
                            "**demo**yu açıp tespiti yine de gör.")

            ships = ss.get("ships_cache", [])
            if ships:
                _render_ships(ships, ss.get("ships_prev", {}), view_zoom=6)
            elif not ss.get("sea_status"):
                st.info("Deniz bölgesi seç → '🚢 Canlı gemileri çek' bas.")


_dashboard()
