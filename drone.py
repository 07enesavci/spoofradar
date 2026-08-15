"""Drone / RemoteID izleme ve spoofing tespiti.

DURUSTLUK NOTU (onemli):
  Dronlar 2026 regülasyonu geregi RemoteID yayinlar (konum, operatör, kimlik)
  — WiFi/Bluetooth uzerinden, YEREL yayin. ADS-B/AIS gibi merkezi bir bulut
  API'si YOKTUR. Canli drone verisi icin YEREL ALICI gerekir:
    - WiFi/Bluetooth sniffer (ornek: ESP32 + RemoteID firmware, ~10$)
    - Ya da OpenDroneID uyumlu alici + bu modul

  Bu modul TESPIT mantigini icerir (ADS-B kodunu drone'a uyarlar). Yerel
  alicidan Drone nesneleri beslenirse spoofing/anomali yakalar. Merkezi
  canli besleme YOK — bu teknolojinin dogasi geregi (yerel yayin).

  Tespit edilenler: sahte drone, klon seri-no, imkansiz hiz, yasak-bolge
  (havaalani/kritik altyapi yakini izinsiz drone), operatör-uzakligi.
"""

from __future__ import annotations

from dataclasses import dataclass

from detectors import haversine

# Drone hiz limiti: tuketici dronlari ~30 m/s, yaris ~50 m/s. Ustu süpheli.
MAX_DRONE_SPEED_MS = 60.0
# Operatör-drone maks makul uzaklik (RemoteID operatör konumu da yayinlar)
MAX_OPERATOR_DIST_M = 8000.0


@dataclass
class Drone:
    serial: str           # RemoteID seri numarasi
    lat: float | None
    lon: float | None
    alt: float | None
    speed: float | None   # m/s
    operator_lat: float | None = None   # operatör konumu (RemoteID yayinlar)
    operator_lon: float | None = None
    timestamp: float = 0.0

    @property
    def has_position(self):
        return self.lat is not None and self.lon is not None


@dataclass
class DroneAlert:
    serial: str
    kind: str
    detail: str
    severity: str


def check_operator_distance(d: Drone) -> DroneAlert | None:
    """Operatör drona makul mesafede mi? Cok uzaksa = spoof/kacak."""
    if not (d.has_position and d.operator_lat is not None):
        return None
    dist = haversine(d.lat, d.lon, d.operator_lat, d.operator_lon)
    if dist > MAX_OPERATOR_DIST_M:
        return DroneAlert(
            d.serial, "operator_far",
            f"Operatör {dist/1000:.1f} km uzakta (makul: <{MAX_OPERATOR_DIST_M/1000:.0f} km). "
            "Sahte konum / yasadışı uçuş şüphesi.", "high")
    return None


def check_drone_speed(prev: Drone, cur: Drone) -> DroneAlert | None:
    if not (prev.has_position and cur.has_position):
        return None
    dt = cur.timestamp - prev.timestamp
    if dt < 0.5:
        return None
    dist = haversine(prev.lat, prev.lon, cur.lat, cur.lon)
    implied = dist / dt
    if implied > MAX_DRONE_SPEED_MS:
        return DroneAlert(
            cur.serial, "impossible_speed",
            f"{implied:.0f} m/s ima edildi — drone için imkansız = spoof.", "high")
    return None


def analyze_drones(prev_by_serial: dict, current: list[Drone],
                   restricted_zones=None) -> list[DroneAlert]:
    """Drone trafigini analiz et. restricted_zones: [(lat,lon,radius_km,ad)]."""
    alerts = []
    seen = {}
    for d in current:
        # Operatör uzakligi
        a = check_operator_distance(d)
        if a:
            alerts.append(a)
        # Hiz
        prev = prev_by_serial.get(d.serial)
        if prev:
            a2 = check_drone_speed(prev, d)
            if a2:
                alerts.append(a2)
        # Klon seri-no
        if d.has_position:
            if d.serial in seen:
                dist = haversine(d.lat, d.lon, seen[d.serial].lat, seen[d.serial].lon)
                if dist > 2000:
                    alerts.append(DroneAlert(
                        d.serial, "duplicate_serial",
                        f"Aynı seri-no iki konumda ({dist/1000:.1f} km). Klon.", "high"))
            else:
                seen[d.serial] = d
        # Yasak bolge
        if restricted_zones and d.has_position:
            for zlat, zlon, zrad, zname in restricted_zones:
                if haversine(d.lat, d.lon, zlat, zlon) / 1000 < zrad:
                    alerts.append(DroneAlert(
                        d.serial, "restricted_zone",
                        f"Yasak bölgede: {zname}. İzinsiz drone.", "high"))
    return alerts


def drone_available() -> bool:
    """Canli drone verisi (yerel alici) yapilandirildi mi?

    Merkezi API yok — yerel RemoteID alicisi gerekir. Varsayilan: yok.
    """
    return False
