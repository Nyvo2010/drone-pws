# Sauron — Drone PWS - Thermal Forest Fire Detection

**Formal title:** Bosbrand detectie drone (PWS).  
**Informal name:** Sauron.

Short project description (edit me).

## Setup

Geen installatie nodig: alleen Python 3 (stdlib, werkt offline).

```bash
python3 tests/test_sauron.py   # 33 tests, moeten allemaal slagen
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

  Alleen `frame` is strikt verplicht. Kleine contractverschillen worden
  geaccepteerd (`temps` i.p.v. `frame`, `heading` i.p.v. `heading_deg`,
  `alt` i.p.v. `alt_msl`, of een genest 24x32-frame), en
  `gps_alt_launch` hoeft maar één keer per vlucht mee: de laptop onthoudt
  hem. Ontbreekt hij toch, dan komen er wel branden maar geen
  coördinaten — geen 400. Een pakket dat écht niet klopt verschijnt als
  `ingest afgewezen: ...` in het logboek, zodat je in het veld ziet wat
  er misgaat in plaats van alleen "niet verbonden".
- Geen separates telemetry-radiolink nodig: alles over één WiFi-verbinding.

### Dashboard (localhost, live view)

```bash
python3 dashboard.py --demo    # zonder hardware: gesimuleerde live-feed
python3 dashboard.py           # echt: wacht op POST /api/ingest (ESP32-forwarder)
```

Open daarna: http://localhost:8000 — live RGB + thermal-canvas + GPS +
branden + logboek. De server luistert standaard op `0.0.0.0:8000`, zodat de
ESP32 op het WiFi-access point naar `http://<laptop-ip>:8000/api/ingest` kan
POSTen; de startup-regel print dat LAN-adres. Alleen lokaal testen kan met
`--host 127.0.0.1`.

De header toont **Sauron**, of er verbinding is (`verbonden` / `niet
verbonden`) en een knop **nieuwe vlucht**. Die knop sluit de huidige vlucht
af, bewaart hem in `logs/` en reset alle live-data (drone, branden, frame,
logboek).

### Branden over meerdere frames

Dezelfde brand houdt hetzelfde ID (`B1`, `B2`, ...; per vlucht weer vanaf
`B1`) zolang hij binnen `track_match_radius_m` (standaard 8 m) terugkomt. Elke brand heeft
`first_seen`, `last_seen` (laatst gemeten tijdstip), `observations` en
`status` (`active`/`lost`). Valt een brand buiten beeld, dan blijft hij
`track_archive_after_s` (120 s) beschikbaar; komt hij binnen die tijd terug,
dan is het weer dezelfde `B1` in plaats van een duplicaat. De UI toont
"uit beeld" met het laatste tijdstip; de marker op het thermische beeld
verdwijnt zolang hij niet actief is. Stopt de datastroom helemaal, dan
markeert de watchdog de branden na de grace-periode als uit beeld en
archiveert ze na 120 s; de header zegt dan "niet verbonden".

### Wanneer er géén coördinaten komen

De brand wordt altijd gemeld, de locatie alleen als die echt te berekenen
is. Zonder coördinaten (met uitleg in de waarschuwing en het logboek):

- GPS-fix zwakker dan 3D (`fix` 0 of 1) — 2D heeft geen bruikbare hoogte;
- ongeldige dronepositie (0,0 of buiten -90..90 / -180..180);
- hoogte ontbreekt (geen `alt_msl` of `gps_alt_launch`);
- AGL <= 0 (drone niet boven het lanceerpunt).

Dode pixels van de MLX90640 en I2C-uitschieters (buiten -20..600 °C)
worden vóór detectie én vóór het canvas door de mediaan van het frame
vervangen. Anders wordt één kapot pixel een "brand" met coördinaten en
schaalt de kleurenkaart op 1200 °C, waardoor de rest van het veld ijs lijkt.

### Vluchtbestanden

Elke vlucht wordt lokaal gelogd als `logs/flight-YYYYMMDD-HHMMSS.jsonl`
(append-only, direct geflusht). Het bestand bevat `flight_start`, alle
`log`-regels, per frame een `ingest` met drone/thermal/branden, en
`fire_new` / `fire_lost` / `fire_reacquired` / `fire_archived` met de
volledige brandinfo. Zo is later per brand terug te vinden wat er gemeten
is. `--log-dir` kiest een andere map.

Met `--capture` wordt ook elk ruw frame (768 waarden, ~5 kB per regel) in
het vluchtbestand bewaard. Daarmee hertune je achteraf de drempels op
echte velddata in plaats van opnieuw te moeten vliegen:

```bash
python3 dashboard.py --capture
python3 -m sauron.replay logs/flight-20261020-101500.jsonl
```

`replay` print een tabel van drempel (dT) × min-area tegen het aantal
frames met een brand, plus het aantal pixels buiten het geldige
temperatuurbereik (je dode-pixel-diagnose).

- `GET /api/flights` — lijst met beschikbare vluchtbestanden
- `GET /api/flights/<naam>` — download één bestand

Batterij en modus zijn placeholders ("—") tot de teamgenoot ze aanlevert.
Autonomie staat uit (stub in `sauron/autonomy.py`); de naad
(State -> suggest_action) ligt klaar voor later.

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
