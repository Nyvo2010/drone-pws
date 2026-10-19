# Sauron — Drone PWS - Thermal Forest Fire Detection

**Formal title:** Bosbrand detectie drone (PWS).  
**Informal name:** Sauron.

Short project description (edit me).

## Setup

Geen installatie nodig: alleen Python 3 (stdlib, werkt offline).

```bash
python3 tests/test_sauron.py   # 14 tests, moeten allemaal slagen
```

## Netwerk Architectures

### WiFi-only (één verbinding, alles via ESP32-gateway)

De laptop verbindt zich met het WiFi-access point van de ESP32-S3-CAM
(SSID `BosbrandDrone`, wachtwoord `12345678`, IP `192.168.4.1`).
De ESP32 fungeert als gateway: het leest de RGB-camera (OV3660),
de thermische sensor (MLX90640) én de GPS van de flight controller
(GEP-M10-DQ via UART4) uit, en stuurt alles over WiFi door naar de laptop.

Datastromen:
- **RGB**: MJPEG-stream `http://192.168.4.1:81/stream` (direct in browser `<img>`)
- **Thermal + GPS**: ESP32 POSTt naar `http://<laptop>:8000/api/ingest`
  met `{frame: [768 floats], drone: {lat, lon, alt_msl, heading_deg,
  fix, sats, hdop}, gps_alt_launch}`
- Geen separates telemetry-radiolink nodig: alles over één WiFi-verbinding.

### Dashboard (localhost, live view)

```bash
python3 dashboard.py --demo    # zonder hardware: gesimuleerde live-feed
python3 dashboard.py           # echt: wacht op POST /api/ingest (ESP32-forwarder)
```

Open daarna: http://localhost:8000 — live RGB + thermal-canvas + GPS +
branden + logboek. Batterij en modus zijn placeholders ("—") tot de
teamgenoot ze aanlevert. Autonomie staat uit (stub in `sauron/autonomy.py`);
de naad (State -> suggest_action) ligt klaar voor later.

## Usage (zonder dashboard)

```bash
python3 main_demo.py            # demo met gesimuleerde brand + leeg veld
```

Eigen frame verwerken (768 floats, rij-majeur) + GPS:

```python
from sauron.pipeline import detect_event

resultaat = detect_event(
    frame_768, drone_lat=52.09, drone_lon=4.31, heading_deg=90.0,
    gps_alt_now=25.0, gps_alt_launch=10.0,
)
print(resultaat["fires"][0]["hotspot_lat"], resultaat["fires"][0]["hotspot_lon"])
```

Zie `sauron/config.py` voor alle drempels en `sauron/gps_nmea.py` voor
NMEA-poortdetectie.
