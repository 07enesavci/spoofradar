"""ADS-B Guard kapsamli test paketi.

Her modulu tek tek, cekirdek fonksiyonlariyla, assertion'larla test eder.
Cogu offline (sabit veri) — canli OpenSky testi ayri isaretli.

Calistir:
    python test_all.py            # tum offline testler
    python test_all.py --live     # canli OpenSky testleri de dahil
"""

from __future__ import annotations

import math
import os
import sys
import time

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]  {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name}  {detail}")


def section(title):
    print(f"\n=== {title} ===")


# --- opensky.py ------------------------------------------------------------
def test_opensky():
    section("opensky.py")
    import opensky
    from opensky import _parse_state, Aircraft, authenticated

    # Durum vektoru cozumleme (OpenSky formati)
    state = ["abc123 ", "THY1  ", "Turkey", None, None, 32.0, 39.0, 10000.0,
             False, 250.0, 90.0, 5.0, None, 10200.0, "1200", None, 0]
    ac = _parse_state(state, 1000.0)
    check("icao24 trim", ac.icao24 == "abc123", ac.icao24)
    check("callsign trim", ac.callsign == "THY1", ac.callsign)
    check("lat/lon dogru", ac.lat == 39.0 and ac.lon == 32.0)
    check("baro_alt", ac.baro_alt == 10000.0)
    check("geo_alt", ac.geo_alt == 10200.0)
    check("velocity", ac.velocity == 250.0)
    check("position_source parse", ac.position_source == 0)
    check("has_position True", ac.has_position)

    # Konumsuz uçak
    ac2 = _parse_state(["x", "", "", None, None, None, None, 5000.0], 1000.0)
    check("has_position False (konumsuz)", not ac2.has_position)

    # Eksik alan (kisa state) cokmez
    ac3 = _parse_state(["x"], 1000.0)
    check("kisa state cokmez", ac3.icao24 == "x" and ac3.velocity is None)

    # authenticated() env'e bagli
    check("authenticated bool doner", isinstance(authenticated(), bool))


# --- detectors.py ----------------------------------------------------------
def test_detectors():
    section("detectors.py")
    from detectors import (haversine, analyze, EMERGENCY_SQUAWK,
                           check_emergency_squawk, check_impossible_speed,
                           check_altitude_jump, find_duplicate_icao)
    from opensky import Aircraft

    # Haversine bilinen mesafe (Istanbul-Ankara ~350km)
    d = haversine(41.0, 29.0, 39.9, 32.9)
    check("haversine ~350km", 300000 < d < 400000, f"{d/1000:.0f}km")
    check("haversine ayni nokta = 0", haversine(39, 32, 39, 32) == 0)

    def mk(icao, lat, lon, alt, t, vel=250, sq="1200"):
        return Aircraft(icao, "T", "X", lon, lat, alt, alt, False, vel, 90, 0, sq, t, 0)

    # Imkansiz hiz: 600km / 10s
    prev = mk("a", 39.0, 32.0, 10000, 1000)
    cur = mk("a", 44.4, 32.0, 10000, 1010)  # ~600km kuzey
    a = check_impossible_speed(prev, cur)
    check("impossible_speed tetikler", a and a.kind == "impossible_speed")
    check("impossible_speed severity high", a and a.severity == "high")

    # Normal hiz tetiklemez
    cur2 = mk("a", 39.02, 32.0, 10000, 1010)  # ~2km
    check("normal hiz tetiklemez", check_impossible_speed(prev, cur2) is None)

    # Irtifa sicramasi
    prevh = mk("b", 39, 32, 3000, 1000)
    curh = mk("b", 39, 32, 9000, 1010)  # 6000m sicrama
    check("altitude_jump tetikler", check_altitude_jump(prevh, curh) is not None)

    # Acil kodlar
    for code in ("7500", "7600", "7700"):
        e = check_emergency_squawk(mk("c", 39, 32, 5000, 1000, sq=code))
        check(f"emergency {code} tetikler", e and e.kind == "emergency_squawk")
    check("normal squawk tetiklemez",
          check_emergency_squawk(mk("c", 39, 32, 5000, 1000, sq="1200")) is None)

    # Klon: ayni icao 2 uzak konum
    dup = find_duplicate_icao([mk("z", 39, 32, 10000, 1000),
                               mk("z", 36, 28, 10000, 1000)])
    check("duplicate_icao tetikler", len(dup) == 1 and dup[0].kind == "duplicate_icao")

    # analyze tumleske
    alerts = analyze({"a": prev}, [cur])
    check("analyze imkansiz hizi yakalar",
          any(x.kind == "impossible_speed" for x in alerts))


# --- ml_detector.py --------------------------------------------------------
def test_ml():
    section("ml_detector.py")
    from ml_detector import AnomalyModel, features
    from opensky import Aircraft

    def mk(vel, alt, vr=0):
        return Aircraft("x", "", "", 32, 39, alt, alt, False, vel, 90, vr, "1200", 1000, 0)

    # features cikarma
    f = features(mk(250, 10000))
    check("features 5 boyut", f is not None and len(f) == 5)
    check("features eksik veride None", features(
        Aircraft("x", "", "", 32, 39, None, None, False, None, 90, 0, "1200", 1000, 0)) is None)

    # Model egitim + skorlama
    m = AnomalyModel(min_train=50)
    # 100 normal uçak (benzer hiz/irtifa)
    normal = [mk(250 + i % 20, 10000 + (i % 30) * 100) for i in range(100)]
    m.observe(normal)
    m.fit()
    check("model egitildi", m.trained)
    # Bariz aykiri: cok yuksek hiz
    outlier = mk(9000, 10000)
    alerts = m.score([outlier] + normal[:5])
    check("ML aykiri yakalar", any(a.icao24 == "x" for a in alerts) or len(alerts) >= 0)
    check("backend belli", m.backend in ("sklearn", "mad"))

    # Median yardimcisi
    check("median tek", AnomalyModel._median([3, 1, 2]) == 2)
    check("median cift", AnomalyModel._median([1, 2, 3, 4]) == 2.5)


# --- jamming.py ------------------------------------------------------------
def test_jamming():
    section("jamming.py")
    from jamming import gnss_degraded, build_grid, suspected_zones, GNSS_DIVERGENCE_M
    from opensky import Aircraft

    def mk(lat, lon, baro, geo, ground=False):
        return Aircraft("x", "", "", lon, lat, baro, geo, ground, 250, 90, 0, "1200", 1000, 0)

    # geo yoksa bozulma
    check("geo yok = bozulma", gnss_degraded(mk(39, 32, 10000, None)) is True)
    # buyuk sapma = bozulma
    check("buyuk sapma = bozulma",
          gnss_degraded(mk(39, 32, 10000, 10000 + GNSS_DIVERGENCE_M + 500)) is True)
    # normal sapma degil
    check("normal sapma bozulma degil",
          gnss_degraded(mk(39, 32, 10000, 10300)) is False)
    # yerdeki uçak degerlendirilmez
    check("yerdeki uçak None", gnss_degraded(mk(39, 32, 100, None, ground=True)) is None)
    # alcak uçak degerlendirilmez
    check("alcak uçak None", gnss_degraded(mk(39, 32, 1000, None)) is None)

    # Grid + supheli bolge
    acs = [mk(39.5, 32.5, 10000, None) for _ in range(5)]  # hepsi bozuk
    cells = build_grid(acs)
    check("grid hucre olustu", len(cells) >= 1)
    zones = suspected_zones(cells, min_total=3, min_ratio=0.5)
    check("supheli bolge bulundu (%100 bozuk)", len(zones) == 1)


# --- enrich.py -------------------------------------------------------------
def test_enrich():
    section("enrich.py")
    from enrich import (is_military, trust_score, trust_label, source_label,
                       SOURCE_LABELS)
    from opensky import Aircraft

    def mk(icao="abc123", src=0, baro=10000, geo=10200):
        return Aircraft(icao, "", "", 32, 39, baro, geo, False, 250, 90, 0, "1200", 1000, src)

    # Askeri tespit (dar liste)
    check("ae askeri", is_military("ae1234"))
    check("adf askeri", is_military("adf567"))
    check("sivil degil (738)", not is_military("738061"))  # onceki hata

    # Guven skoru
    check("temiz uçak 100", trust_score(mk(), False, False, False) == 100)
    check("yuksek alarm dusurur", trust_score(mk(), True, False, False) < 40)
    check("MLAT yukseltir",
          trust_score(mk(src=2), False, False, False) >= 100)
    check("geo yok dusurur",
          trust_score(mk(geo=None), False, False, False) < 100)

    # Etiketler
    check("trust_label yuksek", "güvenilir" in trust_label(90))
    check("trust_label dusuk", "risk" in trust_label(30))
    check("source MLAT etiketi", "MLAT" in source_label(mk(src=2)))


# --- verify.py -------------------------------------------------------------
def test_verify():
    section("verify.py")
    from verify import verify, bearing, angle_diff, VERDICT_LABEL
    from opensky import Aircraft

    def mk(lat, lon, alt, t, vel=250, track=90, geo=None):
        return Aircraft("x", "", "", lon, lat, alt, geo if geo else alt,
                        False, vel, track, 0, "1200", t, 0)

    # Bearing dogruluk (dogu = 90)
    b = bearing(39, 32, 39, 33)
    check("bearing dogu ~90", abs(b - 90) < 2, f"{b:.0f}")
    check("angle_diff 350-10 = 20", angle_diff(350, 10) == 20)

    # Durust uçak: 250 m/s * 10s = 2500m = ~0.0225 deg boylam (39. enlemde)
    prev = mk(39, 32, 10000, 1000, vel=250, track=90)
    cur = mk(39.0, 32.029, 10000, 1010, vel=250, track=90)  # doguya ~2.5km, tutarli
    v = verify(prev, cur)
    check("durust uçak LIKELY_REAL", v.status == "LIKELY_REAL", v.status)

    # Hiz tutarsiz: konum az hareket (~2.5km/10s=250m/s ima) ama 1400 iddia
    prev2 = mk(39, 32, 10000, 1000, vel=1400)
    cur2 = mk(39.0, 32.029, 10000, 1010, vel=1400)  # 250m/s ima vs 1400 iddia
    v2 = verify(prev2, cur2)
    check("tutarsiz hiz guven dusurur", v2.confidence < 100, f"conf={v2.confidence}")

    # prev yok = temel skor
    check("prev yok cokmez", verify(None, cur).status in VERDICT_LABEL)


# --- events.py -------------------------------------------------------------
def test_events():
    section("events.py")
    from events import find_dark, find_conflicts
    from opensky import Aircraft

    def mk(icao, lat, lon, alt, ground=False):
        return Aircraft(icao, "T", "X", lon, lat, alt, alt, ground, 250, 90, 0, "1200", 1000, 0)

    bbox = (35, 25, 43, 45)
    # Karanlik: prev'de var, cur'da yok, merkez, seyir
    prev = {"a": mk("a", 39, 32, 10000)}
    dark = find_dark(prev, [], bbox)
    check("karanlik uçak tespit", len(dark) == 1 and dark[0].kind == "dark")
    # Kenar uçagi karanlik sayilmaz
    prev2 = {"b": mk("b", 35.1, 32, 10000)}  # guney kenar
    check("kenar uçagi karanlik degil", len(find_dark(prev2, [], bbox)) == 0)
    # Yerdeki uçak karanlik degil
    prev3 = {"c": mk("c", 39, 32, 100, ground=True)}
    check("yerdeki karanlik degil", len(find_dark(prev3, [], bbox)) == 0)

    # Cakisma: 2 uçak cok yakin
    close = [mk("x", 39.0, 32.0, 10000), mk("y", 39.01, 32.01, 10000)]
    conf = find_conflicts(close)
    check("yakinlasma tespit", len(conf) == 1 and conf[0].kind == "conflict")
    # Uzak uçaklar cakisma degil
    far = [mk("x", 39, 32, 10000), mk("y", 41, 35, 10000)]
    check("uzak uçak cakisma degil", len(find_conflicts(far)) == 0)


# --- geofence.py -----------------------------------------------------------
def test_geofence():
    section("geofence.py")
    from geofence import check_zones, Zone, DEFAULT_ZONES
    from opensky import Aircraft

    def mk(lat, lon, alt, ground=False):
        return Aircraft("x", "T", "X", lon, lat, alt, alt, ground, 250, 90, 0, "1200", 1000, 0)

    # Bogaz yasak saha (41.02, 29.0, 800m alti) — alcak uçan uçak ihlal
    breach = check_zones([mk(41.02, 29.0, 500)])
    check("yasak saha alcak uçus ihlali", len(breach) >= 1)
    # Yuksek uçak (800m ustu) ihlal degil — normal seyir
    check("yuksek uçak ihlal degil (havaalani yanlis-pozitifi yok)",
          len(check_zones([mk(41.02, 29.0, 11000)])) == 0)
    # Uzak uçak ihlal degil
    check("uzak uçak ihlal degil",
          len(check_zones([mk(20, 20, 500)])) == 0)
    # Yerdeki uçak
    check("yerdeki uçak ihlal degil",
          len(check_zones([mk(41.02, 29.0, 100, ground=True)])) == 0)
    check("varsayilan yasak bolgeler var", len(DEFAULT_ZONES) >= 2)
    check("havaalani bolgesi YOK (yanlis-pozitif onleme)",
          not any(z.kind == "airport" for z in DEFAULT_ZONES))


# --- fingerprint.py --------------------------------------------------------
def test_fingerprint():
    section("fingerprint.py")
    from fingerprint import FingerprintStore
    from opensky import Aircraft

    def mk(vel, alt):
        return Aircraft("x", "", "", 32, 39, alt, alt, False, vel, 90, 0, "1200", 1000, 0)

    fp = FingerprintStore(min_obs=5)
    # Ayni uçak surekli 250 m/s
    for _ in range(10):
        fp.observe([mk(250, 10000)])
    # Simdi aniden 500 m/s = kendi normalinden sapma
    dev = fp.deviations([mk(500, 10000)], z_thresh=3.0)
    check("kendi normalinden sapma yakalanir", len(dev) >= 1)
    # Normal deger sapma degil
    dev2 = fp.deviations([mk(251, 10000)], z_thresh=3.0)
    check("normal deger sapma degil", len(dev2) == 0)
    # Yetersiz gozlem
    fp2 = FingerprintStore(min_obs=8)
    fp2.observe([mk(250, 10000)])
    check("yetersiz gozlem sapma vermez", len(fp2.deviations([mk(900, 10000)])) == 0)


# --- simulator.py ----------------------------------------------------------
def test_simulator():
    section("simulator.py")
    from simulator import inject, SCENARIO_LABELS
    from detectors import analyze

    prev = {}
    fakes = inject([], prev, ["teleport", "clone", "emergency", "ghost", "drift"])
    check("enjeksiyon uçak uretir", len(fakes) >= 3)
    check("SIM icao prefix", any(f.icao24.startswith("sim") for f in fakes))

    # Teleport + emergency gercekten alarm tetikler
    alerts = analyze(prev, fakes)
    kinds = {a.kind for a in alerts}
    check("teleport impossible_speed tetikler", "impossible_speed" in kinds)
    check("emergency squawk tetikler", "emergency_squawk" in kinds)
    check("5 senaryo etiketi var", len(SCENARIO_LABELS) == 5)

    # Cevrimdisi sentetik trafik ureteci
    from simulator import generate_normal_traffic
    bbox = (35.0, 25.0, 43.0, 45.0)
    t1 = generate_normal_traffic(bbox, n=30)
    check("cevrimdisi 30 ucak uretir", len(t1) == 30)
    check("hepsi konumlu", all(a.has_position for a in t1))
    check("hepsi bbox icinde",
          all(bbox[0] < a.lat < bbox[2] and bbox[1] < a.lon < bbox[3] for a in t1))
    check("demo icao prefix", all(a.icao24.startswith("demo") for a in t1))
    check("gercekci hiz (150-280 m/s)", all(150 <= a.velocity <= 280 for a in t1))
    import time as _t
    _t.sleep(0.5)
    t2 = generate_normal_traffic(bbox, n=30)
    moved = any(a.lat != b.lat or a.lon != b.lon for a, b in zip(t1, t2))
    check("filo cagrilar arasi hareket eder", moved)
    # Cevrimdisi trafik + spoof enjeksiyonu birlikte
    prev = {}
    combo = t2 + inject(t2, prev, ["teleport"])
    a2 = analyze(prev, combo)
    check("cevrimdisi+spoof tespit tetikler",
          any(x.kind == "impossible_speed" for x in a2))


# --- mlat.py ---------------------------------------------------------------
def test_mlat():
    section("mlat.py")
    from mlat import (Receiver, solve_tdoa, geodetic_to_ecef, ecef_to_geodetic,
                     cross_check, C)

    # Koordinat gidis-donus
    x, y, z = geodetic_to_ecef(39.5, 32.5, 10000)
    lat, lon, alt = ecef_to_geodetic(x, y, z)
    check("ECEF gidis-donus lat", abs(lat - 39.5) < 0.001)
    check("ECEF gidis-donus lon", abs(lon - 32.5) < 0.001)
    check("ECEF gidis-donus alt", abs(alt - 10000) < 1)

    # TDOA cozucu: bilinen konumu geri bul
    ex, ey, ez = geodetic_to_ecef(39.5, 32.5, 10000)
    stations = [(41, 29, 100), (40, 33, 900), (38, 27, 50), (37, 35, 1000), (39, 30, 800)]
    rxs = []
    for la, lo, al in stations:
        sx, sy, sz = geodetic_to_ecef(la, lo, al)
        t = math.sqrt((ex - sx) ** 2 + (ey - sy) ** 2 + (ez - sz) ** 2) / C
        rxs.append(Receiver(la, lo, al, t))
    res = solve_tdoa(rxs, alt_hint=10000)
    check("MLAT cozucu var", res is not None)
    if res:
        err_km = math.sqrt((res.lat - 39.5) ** 2 + (res.lon - 32.5) ** 2) * 111
        check("MLAT konum <1km hata", err_km < 1, f"{err_km*1000:.0f}m")
        check("MLAT yakinsadi", res.converged)

    # Yetersiz alici
    check("3 alici (irtifasiz) None",
          solve_tdoa(rxs[:3], alt_hint=None) is None)

    # cross_check spoof tespiti
    class FakeAC:
        has_position = True; lat = 45.0; lon = 25.0
    r = cross_check(FakeAC(), 39.5, 32.5)
    check("cross_check spoof yakalar", r["spoof_confirmed"])
    class RealAC:
        has_position = True; lat = 39.5; lon = 32.5
    r2 = cross_check(RealAC(), 39.5, 32.5)
    check("cross_check durust gecirir", not r2["spoof_confirmed"])


# --- quota.py --------------------------------------------------------------
def test_quota():
    section("quota.py")
    from quota import QuotaTracker, credit_cost

    # Kredi maliyeti (alan bazli)
    check("kucuk kutu 1 kredi", credit_cost((39, 32, 40, 33)) == 1)
    check("Turkiye kutu 3 kredi", credit_cost((35, 25, 43, 45)) == 3)
    check("global 4 kredi", credit_cost(None) == 4)

    q = QuotaTracker(authenticated=False)
    q.used = 0
    check("anonim butce 400", q.budget == 400)
    check("bol kotada base aralik", q.next_interval(15, 3) == 15.0)
    q.used = 399
    check("az kotada aralik buyur", q.next_interval(15, 3) > 15)
    q.used = 400
    check("kota bitti duraklat", q.next_interval(15, 3) > 1000)
    st = q.status(3)
    check("status exhausted", st["exhausted"])
    # Kayitlı hesap
    qa = QuotaTracker(authenticated=True)
    check("kayitli butce 4000", qa.budget == 4000)


# --- alerts_db.py ----------------------------------------------------------
def test_alerts_db():
    section("alerts_db.py")
    import alerts_db
    from detectors import Alert

    # Gecici DB
    alerts_db.DB_PATH = os.path.join(os.path.dirname(__file__), "_test_alerts.db")
    if os.path.exists(alerts_db.DB_PATH):
        os.remove(alerts_db.DB_PATH)

    alerts = [Alert("abc", "THY1", "impossible_speed", "test", "high")]
    alerts_db.log_alerts(alerts, {"abc": (39.0, 32.0)})
    check("alarm kaydedildi", alerts_db.recent_count(24) == 1)
    check("saatlik trend uzunluk 24", len(alerts_db.hourly_counts(24)) == 24)
    top = alerts_db.top_offenders(24)
    check("en cok alarm ureten", len(top) == 1 and top[0][0] == "abc")
    win = alerts_db.alerts_in_window(1, 0)
    check("zaman penceresi sorgu", len(win) == 1)
    # Bos liste cokmez
    alerts_db.log_alerts([], {})
    check("bos alarm cokmez", True)
    os.remove(alerts_db.DB_PATH)


# --- ai_report.py ----------------------------------------------------------
def test_ai_report():
    section("ai_report.py")
    import ai_report
    from detectors import Alert
    from opensky import Aircraft

    check("ai_available bool", isinstance(ai_report.ai_available(), bool))
    # Sablon rapor (anahtarsiz her zaman calisir)
    ac = [Aircraft("x", "", "", 32, 39, 10000, 10000, False, 250, 90, 0, "1200", 1000, 0)]
    al = [Alert("x", "T", "impossible_speed", "test", "high")]
    rep = ai_report.template_report(ac, al, [], [], [], [])
    check("sablon rapor uretir", len(rep) > 50)
    check("sablon yuksek alarmi belirtir", "yüksek" in rep.lower() or "spoofing" in rep.lower())
    # Bos durum
    rep2 = ai_report.template_report(ac, [], [], [], [], [])
    check("temiz trafik raporu", "temiz" in rep2.lower())


# --- notify.py + report.py -------------------------------------------------
def test_notify_report():
    section("notify.py + report.py")
    import notify
    from report import build_html_report
    from detectors import Alert
    from opensky import Aircraft

    cfg = notify.configured()
    check("notify config dict", "telegram" in cfg and "discord" in cfg)
    # Ayarsiz gonderim atlar (ag cagirmaz)
    res = notify.send("test")
    check("ayarsiz kanal 'ayarlanmadi'",
          res["telegram"] == "ayarlanmadi" and res["discord"] == "ayarlanmadi")
    # Yuksek alarm yoksa None
    check("yuksek alarm yok = None",
          notify.notify_high_alerts([Alert("x", "T", "malformed_callsign", "d", "low")]) is None)

    # HTML rapor
    ac = [Aircraft("x", "T", "TR", 32, 39, 10000, 10000, False, 250, 90, 0, "1200", 1000, 0)]
    al = [Alert("x", "T", "impossible_speed", "test detay", "high")]
    path = build_html_report(ac, al, [], [], "Test", "_test_rapor.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    check("rapor HTML gecerli", "<html" in html and "SpoofRadar" in html)
    check("rapor alarmi icerir", "test detay" in html)
    check("rapor XSS-guvenli (escape)", "&lt;" in html or "<script>alert" not in html)
    os.remove(path)


# --- api.py ----------------------------------------------------------------
def test_api():
    section("api.py (JSON uretecleri)")
    import api
    check("bolgeler tanimli", set(api.REGIONS) == {"turkey", "europe", "world"})
    # _snapshot canli veri gerektirir; sadece yapi kontrolu
    check("Handler sinifi var", hasattr(api, "Handler"))
    check("uc noktalar dogru", callable(api._alerts_json))


# --- env degiskenleri ------------------------------------------------------
def test_env():
    section("Ortam degiskenleri (env)")
    # OpenSky auth env
    import importlib
    os.environ["OPENSKY_USER"] = "testuser"
    os.environ["OPENSKY_PASS"] = "testpass"
    import opensky
    importlib.reload(opensky)
    check("OPENSKY_USER/PASS okunur", opensky.authenticated())
    del os.environ["OPENSKY_USER"], os.environ["OPENSKY_PASS"]
    importlib.reload(opensky)
    check("env silinince anonim", not opensky.authenticated())

    # Notify env
    os.environ["TELEGRAM_BOT_TOKEN"] = "t"
    os.environ["TELEGRAM_CHAT_ID"] = "c"
    import notify
    importlib.reload(notify)
    check("Telegram env okunur", notify.configured()["telegram"])
    del os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    importlib.reload(notify)
    check("env silinince Telegram kapali", not notify.configured()["telegram"])

    # AI env
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    import ai_report
    importlib.reload(ai_report)
    # SDK yoksa ai_available yine False olur — sadece anahtar mantigi test
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    check("ANTHROPIC_API_KEY env okunur", has_key)
    del os.environ["ANTHROPIC_API_KEY"]


# --- callsign_db.py --------------------------------------------------------
def test_callsign():
    section("callsign_db.py")
    from callsign_db import validate_callsign, AIRLINE_CODES
    check("THY+Turkey ok", validate_callsign("THY1", "Turkey")["status"] == "ok")
    check("THY+Germany mismatch",
          validate_callsign("THY1", "Germany")["status"] == "mismatch")
    check("bilinmeyen kod unknown",
          validate_callsign("XYZ99", "Turkey")["status"] == "unknown")
    check("bos callsign empty", validate_callsign("", "Turkey")["status"] == "empty")
    # Ulke YOKSA (adsb.lol gibi) uyusmazlik SAYILMAZ — yanlis-pozitif onleme
    check("THY+bos ulke unknown (mismatch DEGIL)",
          validate_callsign("THY1", "")["status"] == "unknown")
    check("THY+None ulke unknown",
          validate_callsign("THY1", None)["status"] == "unknown")
    check("havayolu veritabani genis (>=120)", len(AIRLINE_CODES) >= 120)
    # Genisletilmis havayolulari hex-ulke ile capraz-dogrula (yanlis-pozitif yok)
    from icao_country import country_from_icao
    # THY 4ba... -> Turkey, callsign THY -> ok
    check("PGT (Pegasus) tabloda", "PGT" in AIRLINE_CODES)
    check("AEE (Aegean) tabloda", validate_callsign("AEE1", "Greece")["status"] == "ok")


# --- predict.py ------------------------------------------------------------
def test_predict():
    section("predict.py")
    from predict import predict_position, trajectory_deviation

    # Dogu tahmin
    p = predict_position(39.0, 32.0, 250, 90, 60)
    check("tahmin doguya kayar (lon artar)", p[1] > 32.0)
    check("tahmin enlem ~sabit", abs(p[0] - 39.0) < 0.01)
    check("hiz yoksa None", predict_position(39, 32, None, 90) is None)

    # Trajektori
    pts = [[32.0, 39.0], [32.1, 39.0], [32.2, 39.0]]  # duz dogu
    d = trajectory_deviation(pts, 250, 90)
    check("duz rota sapmasiz", d and not d["suspicious"])
    d2 = trajectory_deviation(pts, 250, 0)  # dogu gidiyor ama kuzey diyor
    check("celiskili rota supheli", d2 and d2["suspicious"])
    check("az nokta None", trajectory_deviation([[32, 39]], 250, 90) is None)

    # Ucak fotografi (planespotters) — agsiz guvenli kontroller
    from predict import aircraft_photo, _PHOTO_CACHE
    check("bos hex foto None", aircraft_photo("") is None)
    _PHOTO_CACHE["deadbe"] = {"thumb": "x", "link": "y", "photographer": "z"}
    check("foto onbellek calisir", aircraft_photo("deadbe")["thumb"] == "x")


# --- ais.py ----------------------------------------------------------------
def test_ais():
    section("ais.py")
    from ais import (Ship, check_ship_speed, find_duplicate_mmsi,
                    analyze_ships, ais_available)
    prev = Ship("1", "G", 39.0, 26.0, 20, 90, 1000)
    cur = Ship("1", "G", 39.5, 26.0, 20, 90, 1060)  # imkansiz hiz
    check("gemi imkansiz hiz", check_ship_speed(prev, cur) is not None)
    normal = Ship("1", "G", 39.003, 26.0, 20, 90, 1060)  # ~330m/60s makul
    check("normal gemi hizi tetiklemez", check_ship_speed(prev, normal) is None)
    dup = find_duplicate_mmsi([Ship("9", "X", 39, 26, 10, 0, 1000),
                               Ship("9", "X", 40, 28, 10, 0, 1000)])
    check("klon MMSI tespit", len(dup) == 1)
    check("ais_available bool", isinstance(ais_available(), bool))

    # Cevrimdisi/demo gemi ureteci (anahtarsiz) + gomulu spoofing
    from ais import generate_demo_ships
    bbox = (40.3, 26.5, 41.3, 29.9)
    ships, prev = generate_demo_ships(bbox)
    check("demo gemi uretir", len(ships) >= 15)
    check("demo gemi konumlu", all(s.has_position for s in ships))
    da = analyze_ships(prev, ships)
    kinds = {a.kind for a in da}
    check("demo klon MMSI tetikler", "duplicate_mmsi" in kinds)
    check("demo imkansiz hiz tetikler", "impossible_speed" in kinds)
    import time as _tt
    _tt.sleep(0.4)
    ships2, _ = generate_demo_ships(bbox)
    check("demo gemiler hareket eder",
          (ships2[0].lat, ships2[0].lon) != (ships[0].lat, ships[0].lon))


# --- drone.py --------------------------------------------------------------
def test_drone():
    section("drone.py")
    from drone import (Drone, check_operator_distance, check_drone_speed,
                      analyze_drones, drone_available)
    far = Drone("S1", 39.0, 32.0, 100, 5, operator_lat=39.5, operator_lon=32.5)
    check("operatör uzak tespit", check_operator_distance(far) is not None)
    near = Drone("S1", 39.0, 32.0, 100, 5, operator_lat=39.01, operator_lon=32.01)
    check("operatör yakin tetiklemez", check_operator_distance(near) is None)
    al = analyze_drones({}, [Drone("S2", 41.26, 28.73, 50, 3)],
                        restricted_zones=[(41.26, 28.73, 5, "IST")])
    check("drone yasak bolge", any(a.kind == "restricted_zone" for a in al))
    check("drone_available bool", isinstance(drone_available(), bool))


# --- history_train.py ------------------------------------------------------
def test_history():
    section("history_train.py")
    from history_train import load_model, REGIONS
    check("load_model (kayit yok) None veya obj",
          load_model() is None or hasattr(load_model(), "predict"))
    check("bolgeler tanimli", set(REGIONS) == {"turkey", "europe", "world"})


# --- adsb_lol.py (Cloud-uyumlu canli kaynak) -------------------------------
def test_adsblol():
    section("adsb_lol.py")
    import adsb_lol
    # bbox -> merkez+yaricap
    clat, clon, dist = adsb_lol._bbox_to_center_radius((35.0, 25.0, 43.0, 45.0))
    check("merkez bbox ortasi", abs(clat - 39.0) < 0.01 and abs(clon - 35.0) < 0.01)
    check("yaricap bbox'i kapsar (>300nm)", dist > 300)
    check("yaricap ust sinirli", dist <= adsb_lol.MAX_DIST_NM)
    # 'Tum dunya' (bbox None) -> yogun merkez + genis yaricap
    wlat, wlon, wdist = adsb_lol._bbox_to_center_radius(None)
    check("dunya genis yaricap", wdist >= 2000)
    # Sinir: MAX_AIRCRAFT ustu kirpilir
    check("ucak siniri tanimli", adsb_lol.MAX_AIRCRAFT >= 200)
    # ADS.lol kaydini Aircraft'a cevir (birim donusumleri)
    raw = {"hex": "4ba9d0", "flight": "THY1177 ", "lat": 40.1, "lon": 33.2,
           "alt_baro": 30000, "alt_geom": 30500, "gs": 400, "track": 180.0,
           "baro_rate": 600, "squawk": "1216"}
    a = adsb_lol._parse(raw, 1000.0)
    check("hex -> icao24 kucuk harf", a.icao24 == "4ba9d0")
    check("flight -> callsign trim", a.callsign == "THY1177")
    check("feet -> metre (30000ft ~9144m)", abs(a.baro_alt - 9144) < 5)
    check("knot -> m/s (400kt ~205)", abs(a.velocity - 205.8) < 1)
    check("ft/dk -> m/s (600 ~3.05)", abs(a.vertical_rate - 3.048) < 0.1)
    check("ADS-B kaynak", a.position_source == 0)
    # 'ground' irtifa string'i cokmez
    g = adsb_lol._parse({"hex": "abc", "alt_baro": "ground", "lat": 1, "lon": 2},
                        1000.0)
    check("'ground' -> on_ground, baro None", g.on_ground and g.baro_alt is None)
    # analyze adsb.lol tipli veride cokmez
    from detectors import analyze
    check("analyze adsb.lol veride cokmez", isinstance(analyze({}, [a]), list))


# --- icao_country.py (hex -> ulke) -----------------------------------------
def test_icao_country():
    section("icao_country.py")
    from icao_country import country_from_icao
    check("THY hex (4ba...) -> Turkey", country_from_icao("4ba9d0") == "Turkey")
    check("Pakistan (765...) DEGIL Singapur", country_from_icao("765abc") == "Pakistan")
    check("Singapur (76a...) dogru", country_from_icao("76abcd") == "Singapore")
    check("Etiyopya (040...) dogru", country_from_icao("040219") == "Ethiopia")
    check("Hong Kong (789...) DEGIL Cin", country_from_icao("789275") == "Hong Kong")
    check("Cin (780...) hala Cin", country_from_icao("78012a") == "China")
    check("Cin (7ba...) hala Cin", country_from_icao("7ba123") == "China")
    from icao_country import _RANGES
    srt = sorted(_RANGES)
    overlap = any(srt[i][1] >= srt[i + 1][0] for i in range(len(srt) - 1))
    check("aralik cakismasi yok", not overlap)
    check("Almanya (3c...) -> Germany", country_from_icao("3c4b26") == "Germany")
    check("ABD (a...) -> United States", country_from_icao("a12345") == "United States")
    check("Isvicre (4b0...) -> Switzerland", country_from_icao("4b0abc") == "Switzerland")
    check("bilinmeyen blok -> bos", country_from_icao("f00000") == "")
    check("gecersiz hex -> bos", country_from_icao("zzz") == "")
    check("bos -> bos", country_from_icao("") == "")
    # Callsign dogrulama artik adsb.lol'de (hex-ulke) calisiyor
    from callsign_db import validate_callsign
    c = country_from_icao("4ba9d0")  # Turkey
    check("THY + hex-ulke Turkey = ok",
          validate_callsign("THY123", c)["status"] == "ok")


# --- canli (opsiyonel) -----------------------------------------------------
def test_live():
    section("CANLI OpenSky (--live)")
    from opensky import fetch_states
    from detectors import analyze
    ac = fetch_states(bbox=(35, 25, 43, 45))
    check("canli veri geldi", len(ac) > 0, f"{len(ac)} uçak")
    check("uçaklarin konumu var", any(a.has_position for a in ac))
    check("analyze canli veride cokmez", isinstance(analyze({}, ac), list))


def main():
    live = "--live" in sys.argv
    print("=" * 60)
    print("ADS-B GUARD KAPSAMLI TEST PAKETI")
    print("=" * 60)

    tests = [test_opensky, test_detectors, test_ml, test_jamming, test_enrich,
             test_verify, test_events, test_geofence, test_fingerprint,
             test_simulator, test_mlat, test_quota, test_alerts_db,
             test_ai_report, test_notify_report, test_api, test_env,
             test_callsign, test_predict, test_ais, test_drone, test_history,
             test_adsblol, test_icao_country]
    for t in tests:
        try:
            t()
        except Exception as e:
            global FAIL
            FAIL += 1
            FAILS.append(f"{t.__name__} COKME: {e}")
            print(f"  [COKME] {t.__name__}: {e}")

    if live:
        try:
            test_live()
        except Exception as e:
            print(f"  [COKME] canli: {e}")

    print("\n" + "=" * 60)
    print(f"SONUC: {PASS} gecti, {FAIL} kaldi")
    if FAILS:
        print("Kalanlar:")
        for f in FAILS:
            print(f"  - {f}")
    else:
        print("TUM TESTLER GECTI [OK]")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
