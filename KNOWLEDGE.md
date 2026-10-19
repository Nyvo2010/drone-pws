# Bosbrand detectie drone — kennisbank

## Projectoverzicht

- Projectnaam: Bosbrand detectie drone
- Informele codenaam: Sauron
- Doel: Een drone ontwikkelen die bosbranden kan herkennen en lokaliseren door middel van RGB- en thermische beeldvorming, live dataversturing naar een laptop en GPS-locatieweergave.
- Werkmodus: Offline, zonder internetverbinding
- Netwerk: De drone maakt een eigen WiFi-access point aan voor communicatie met een laptop

## Doelstellingen

1. RGB-beelden vastleggen met een OV3660-camera
2. Thermische beelden vastleggen met een MLX90640
3. Beide beelden combineren in één overlay
4. Hotspots detecteren
5. GPS-locatie tonen
6. Data live naar een laptop sturen
7. Zonder internet werken
8. Een eigen WiFi-netwerk maken vanuit een ESP32

---

## Dronehardware

### Frame

- Model: HaoyeRC 7 Inch Carbon Fiber Frame Kit
- Functie: Draagt alle dronecomponenten

### Flight controller stack

- Model: GEPRC TAKER F722 BT 60A Stack
- Bestaat uit:
  - GEPRC TAKER F722 BT flight controller
  - GEPRC 60A 4-in-1 ESC
- Functies:
  - Vluchtbesturing
  - GPS-interface
  - Receiver-interface
  - Motoraansturing
  - Telemetrie

### Motoren

- Model: 4x EMAX ECO III 2808 1300KV
- Configuratie: 7 inch drone, 6S LiPo
- Motorindeling:
  - M1 = Voor rechts
  - M2 = Achter rechts
  - M3 = Achter links
  - M4 = Voor links
- Aansluitingen:
  - Motor FR → ESC M1
  - Motor RR → ESC M2
  - Motor RL → ESC M3
  - Motor FL → ESC M4

### GPS

- Model: GEPRC GEP-M10-DQ
- Functies:
  - GPS
  - Kompas
  - Barometer
- Aansluitingen:
  - GPS 5V → FC 5V
  - GPS GND → FC GND
  - GPS TX → FC RX4
  - GPS RX → FC TX4
- UART: UART4

### Radio controller

- Model: RadioMaster T8L ELRS
- Communicatie met:
  - RadioMaster XR1 ELRS Receiver

### Receiver

- Model: RadioMaster XR1 ExpressLRS
- Aansluitingen:
  - XR1 5V → FC 5V
  - XR1 GND → FC GND
  - XR1 TX → FC RX2
  - XR1 RX → FC TX2
- UART: UART2

---

## Camerasysteem

### ESP32-board

- Model: Heemol ESP32-S3-CAM
- Processor: ESP32-S3
- Specificaties:
  - 16 MB Flash
  - 8 MB PSRAM
  - WiFi
  - Bluetooth
  - USB-C
  - CH340 USB-interface
- Functie:
  - RGB-camera uitlezen
  - Thermal camera uitlezen
  - WiFi access point hosten
  - Webserver draaien
  - Data versturen naar laptop

### RGB-camera

- Model: OV3660
- Functie: RGB-videobeelden en JPEG-stream
- Geintegreerd op het ESP32-bord

### Camera pinout

```cpp
#define PWDN_GPIO_NUM  -1
#define RESET_GPIO_NUM -1

#define XCLK_GPIO_NUM  15

#define SIOD_GPIO_NUM  4
#define SIOC_GPIO_NUM  5

#define VSYNC_GPIO_NUM 6
#define HREF_GPIO_NUM  7

#define Y4_GPIO_NUM    8
#define Y3_GPIO_NUM    9
#define Y5_GPIO_NUM    10
#define Y2_GPIO_NUM    11
#define Y6_GPIO_NUM    12

#define PCLK_GPIO_NUM  13

#define Y9_GPIO_NUM    16
#define Y8_GPIO_NUM    17
#define Y7_GPIO_NUM    18
```

- Camera model: `CAMERA_MODEL_HEEMOL_S3_CAM`
- Arduino IDE board: `ESP32S3 Dev Module`

### Thermische camera

- Model: MLX90640
- Specificaties:
  - 32 x 24 pixels
  - 768 temperatuurpunten
  - I²C-interface

### Aansluitingen MLX90640

- MLX90640 VIN → ESP32 3V3
- MLX90640 GND → ESP32 GND
- MLX90640 SDA → ESP32 GPIO1
- MLX90640 SCL → ESP32 GPIO2

### I²C-initialisatie

```cpp
Wire.begin(1, 2);
```

### Outputformaat

- `float frame[768];`
- Of: een 32 x 24 temperatuurmatrix

---

## ESP32-voeding

- Het camerasysteem is niet gekoppeld aan de dronevoeding
- Voeding:
  - 18650 batterij
  - 18650 naar 5V-converter
  - ESP32
- Aansluitingen:
  - Converter 5V OUT → ESP32 5V
  - Converter GND → ESP32 GND

## Drone-accu

- Type: 6S LiPo
- Voedt:
  - ESC
  - Flight Controller
  - GPS
  - Receiver
  - Motoren
- Niet de ESP32

---

## Netwerkconfiguratie

- ESP32 draait als WiFi access point
- Geen router gebruiken
- SSID: `BosbrandDrone`
- Wachtwoord: `12345678`
- Code:

```cpp
WiFi.softAP(
    "BosbrandDrone",
    "12345678"
);
```

- Standaard IP: `192.168.4.1`

---

## Softwarearchitectuur

### ESP32-taken

1. OV3660 uitlezen
2. MLX90640 uitlezen
3. WiFi-host aanmaken
4. CameraWebServer draaien
5. Thermal data versturen
6. RGB-stream versturen

### Laptopsoftware

- Programmeertaal: Python
- Bibliotheken:
  - `opencv-python`
  - `numpy`
  - `matplotlib`
  - `requests`
- Installatie:

```bash
pip install opencv-python
pip install numpy
pip install matplotlib
pip install requests
```

---

## Dataverkeer

### RGB-stream

- Type: MJPEG
- URL: `http://192.168.4.1:81/stream`

### Thermal data

- Type: JSON of CSV
- Voorbeeld:

```json
[
  23.1,
  23.0,
  22.9,
  ...
]
```

- Totaal: 768 waarden

---

## Systeemsamenvatting

De drone combineert een RGB-camera en een thermische sensor op een ESP32-S3, maakt een eigen WiFi-netwerk aan en stuurt live beelden en temperatuurdata naar een laptop. De laptop verwerkt deze data in Python, waarbij RGB- en thermische informatie worden gecombineerd voor hotspotdetectie en locatiebepaling.

## Outdoor software-idee: veldgebruik met radioverbinding

### Doel

De software moet buiten werken in de echte omgeving: de drone moet live RGB en thermische beelden tonen, hotspots detecteren, de dronepositie tonen op een kaart en de hotspotlocatie koppelen aan een exacte wereldlocatie.

### Kernprincipe

De software bestaat uit 4 lagen:

1. Sensorlaag
   - ESP32 leest RGB-camera uit
   - ESP32 leest MLX90640 uit
   - Flight controller leest GPS, kompas en status uit

2. Communicatielaag
   - ESP32 camera-link via WiFi access point
   - Flight controller telemetry via radiolink naar laptop
   - Laptop gebruikt externe antenne / USB-radiolink voor bereikvergroting

3. Verwerkingslaag
   - Python verwerkt RGB-frame
   - Python verwerkt thermische matrix 32x24
   - Python detecteert hotspots
   - Python berekent dronepositie en hotspotlocatie

4. Visualisatielaag
   - hoofdscherm: RGB + thermische overlay
   - zijpaneel: complete thermische kaart
   - onderpaneel: kaart met dronepositie en hotspot

### Exacte gebruikersinterface

De laptopsoftware toont 3 views tegelijk:

- View 1: RGB + overlay
  - links of centraal: live RGB-frame
  - bovenop: thermische hotspots in kleur
  - labels: hotspotnummer, maximale temperatuur, locatie in beeld

- View 2: Thermal panel
  - volledige 32x24 temperatuurmatrix als heatmap
  - kleurenschaal van koud naar heet
  - maximale temperatuur, gemiddelde temperatuur
  - hotspotlijst met XY-coördinaten in camera-frame

- View 3: Map panel
  - exacte locatie van de drone op kaart
  - hotspotlocatie als marker
  - afstand van drone tot hotspot
  - route of last known position

### Functionele flow

1. ESP32 maakt WiFi access point aan
   - SSID: BosbrandDrone
   - wachtwoord: 12345678
   - standaard IP: 192.168.4.1

2. Laptop verbindt zich met deze WiFi
   - externe WiFi-antenne op laptop of USB WiFi-adapter
   - voor groter bereik: hogere gain antenna of juiste RF-band

3. ESP32 stuurt RGB-stream naar laptop
   - URL: http://192.168.4.1:81/stream
   - formaat: MJPEG

4. ESP32 stuurt thermische data naar laptop
   - JSON of CSV met 768 waarden
   - omgezet naar 32x24 matrix

5. Flight controller stuurt GPS-telemetrie naar laptop
   - via MAVLink of NMEA
   - latitude, longitude, altitude, heading, snelheid

6. Laptop combineert alles
   - dronepositie = FC GPS
   - hotspotpositie = berekend uit thermal + dronepositie + heading + camerahoek
   - alle data worden in één dashboard getoond

### Hardware-architectuur buiten gebruik

- ESP32 camera systeem
  - op drone gemonteerd
  - eigen WiFi access point
  - externe RF-antenne op ESP32-onderdeel voor betere bereik

- Flight controller
  - ontvangt GPS-signalen
  - stuurt telemetrie over een radiolink naar laptop
  - gebruikt eigen telemetry radio of ELRS-telemetry

- Laptop
  - USB-radiolink / USB-telemetry-adapter
  - WiFi USB-adapter voor verbinding met ESP32
  - draait de dashboardsoftware

### Radio-opstelling voor buitengebruik

- Camera-link (ESP32): WiFi / access point op 2.4 GHz of 5 GHz, afhankelijk van hardware en bereik
- Telemetry-link (FC): MAVLink over telemetry radio, typisch 915 MHz, 868 MHz of 2.4 GHz wanneer gebruik wordt gemaakt van ELRS
- USB-antenne op laptop: alleen correct gebruiken als deze past bij de gekozen frequentie en het gekozen radiosysteem

> Belangrijk: een algemene '4.2 GHz USB-antenne' is niet automatisch geschikt voor WiFi of telemetrie. De antenne en radiofrequentie moeten exact overeenkomen met het gebruikte systeem. Voor WiFi zijn meestal 2.4GHz of 5GHz banden relevant; voor telemetry-radio is vaak 868/915MHz of 2.4GHz relevant.

### Drie gekoppelde datastreams

- Camera stream: ESP32 → WiFi → laptop
- Thermal stream: ESP32 → WiFi → laptop
- Telemetry stream: FC → radio → laptop

### GPS-vraag: waar komt de locatie vandaan?

De GPS is niet op de ESP32 aangesloten. Daarom moet de positie van de drone worden gelezen van de flight controller:

- GPS is aangesloten op UART4 van de flight controller
- FC geeft de locatie door via MAVLink/telemetrie
- laptop leest die positie via telemetry-radio of USB-serial
- de app gebruikt deze GPS-coördinaten om de drone te tonen op de kaart

Dus:

- ESP32 = beeldsensoren
- Flight controller = navigatie en positie
- Laptop = samenvatting en mapping

### Exacte software-structuur

```text
[ESP32 RGB Camera] --WiFi--> [Laptop App]
        |                      |
        +-- Thermal data ------> [Python Dashboard]
                                  |
[Flight Controller GPS] --Telemetry--> [Python Dashboard]
                                  |
                         +----------+----------+
                         |                      |
                 [RGB + Thermal Overlay]   [Map + GPS]
                         |                      |
                 [Hotspot Detection]   [Drone Position]
```

### Softwarecomponenten

- Camera receiver module
  - haalt MJPEG RGB-stream op
  - haalt thermal JSON/CSV op

- Telemetry reader module
  - leest MAVLink of NMEA-data uit de telemetry-USB of serialpoort
  - parseert latitude, longitude, altitude

- Thermal processing module
  - zet 768 waarden om naar 32x24 matrix
  - bepaalt hotspotregionen
  - berekent max temp en hotspotcenter

- Geo-mapping module
  - plaats drone op kaart met GPS-coördinaten
  - plaats hotspot op kaart met berekende locatie
  - toont afstand en richtingsinformatie

- Dashboard frontend
  - HTML + JavaScript / React / Streamlit / Flask page
  - live update zonder browser-refresh

### Praktische implementatieaanbeveling

- Gebruik een Python backend met Flask of FastAPI
- Gebruik een eenvoudige webinterface met HTML, CSS en JavaScript
- Gebruik Leaflet voor de kaartweergave
- Gebruik OpenCV + NumPy voor thermische beeldverwerking
- Gebruik pymavlink voor flight controller telemetry
- Gebruik een websocket of polling voor live updates

### Reële veldworkflow

1. Laptop verbindt zich met ESP32 WiFi access point
2. Laptop verbindt zich met telemetry radio van flight controller
3. App start en toont alle data live
4. Drone vliegt boven het gebied
5. Camera detecteert warmte
6. Hotspots worden gemarkeerd
7. Laptop toont exacte positie van drone en hotspot op kaart
8. Operator ziet live waar brandhaard zich bevindt

## Relevante projectgegevens

- Doelgebied: bosbrand detectie
- Werkvorm: drone met offline communicatie
- Sensoren: RGB + thermische camera + GPS
- Besturingsplatform: ESP32-S3 + flight controller stack
- Datacommunicatie: WiFi access point voor camera en telemetry radio voor GPS/positioning
- Gebruikte paradigma: combinatie van camera-beeld, thermische hotspotdetectie en GPS-kaartlocatie

## Detectie-ontwerpbeslissingen (Sauron laptopkant, vastgelegd)

- Warmtecamera kijkt RECHT NAAR BENEDEN (pitch vast -90); RGB kijkt VOORUIT.
  Geen RGB-thermal overlay: kijkrichtingen verschillen, registratie is uit scope.
- MLX90640 wide-variant als aanname: FOV 110 x 75 graden (instelbaar in `sauron/config.py`).
- GPS = NMEA (GGA/RMC); seriële poort nog onbekend, `gps_nmea.list_candidate_ports()` helpt zoeken.
- NMEA-hoogte is MSL; AGL = GPS(nu) - GPS(lancering). Geen geoid-wiskunde nodig (zelfde datum).
- Locatieformule per hotspot-pixel: pixel -> hoek (FOV) -> grondmeters (tan) ->
  kompasrotatie (heading, sin/cos) -> lat/lon (platte aarde). Centrum-pixel = recht eronder.
- Testbereik: 5-30 m AGL, bijna geen wind (geen driftcompensatie).
- Drempels (startwaarden, kalibreren in het veld): threshold = ambient + 12 C,
  min-area 3 px, brand bij delta >= 10 C en abs >= 40 C.
- Implementatie: alleen Python-stdlib (geen numpy/opencv nodig), zie `sauron/` + `main_demo.py`.
- ALLE processing draait op de laptop (ESP32/FC leveren alleen ruwe data aan).
- Dashboard: `python3 dashboard.py [--demo]` -> http://localhost:8000 (één HTML-bestand,
  geen framework, offline). Live RGB-img (ESP32-stream), thermal-canvas (32x24),
  drone-GPS + hotspot-tabel + logboek; batterij/modus zijn placeholders.
- Naad voor teamgenoot: POST /api/ingest {frame (768), drone, gps_alt_launch}.
- Naad voor later autonoom vliegen: State (lezen) -> autonomy.suggest_action (stub, uit).
  Besturing stuurt nooit hardware aan; commando's lopen via de FC-link.
- Dashboard-UI: donker canvas, één mono-font, 1px hairline-panelen, 4px radius
  alleen op interactieve elementen, geen schaduwen of gradients. Geen Google
  Fonts of andere netwerkbronnen: de UI moet offline werken.
- Informatiehiërarchie dashboard: camera's bovenaan (primair), branden/
  telemetrie/logboek eronder. Detail (score, delta, reasons, coördinaten)
  zit achter één klik per brand; placeholders en lege velden worden verborgen
  in plaats van als "—"-ruis getoond. De topbar is compact: alleen SAURON,
  verbonden/niet verbonden en de nieuwe-vlucht-knop.
- Camera-boxen volgen de echte beeldverhouding: thermisch is 32x24 = 4:3,
  RGB wordt bij het laden uit naturalWidth/naturalHeight gelezen (fallback
  16:9). De boxen krijgen samen de grootst mogelijke maat binnen de
  camerarij, zodat beide beelden zonder vervorming passen.
- Brand-tracking: dezelfde brand houdt hetzelfde ID als hij binnen
  `track_match_radius_m` (8 m) terugkomt; zonder locatie wordt op pixelafstand
  (4 px) gematcht. Na 2,5 s niet gezien = `lost` (last_seen blijft staan);
  binnen 120 s terug = dezelfde track, daarna gearchiveerd. Dit voorkomt
  duplicaten bij korte dropouts en bij een brand die even uit beeld valt.
  Stopt de datastroom helemaal, dan laat de watchdog de brandtijd gewoon
  doorlopen: na 2,5 s wordt de track `lost`, na 120 s gearchiveerd.
- Logboek = gebeurtenissen, niet elke frame dezelfde brand: eerste data,
  data hervat, GPS-fixwijziging, nieuwe/uit/terug/gearchiveerde brand,
  waarschuwingen. De per-frame brandinfo staat in het vluchtbestand.
- Vluchtbestand: `logs/flight-YYYYMMDD-HHMMSS.jsonl`, append-only en direct
  geflusht. Bevat flight_start, log, ingest (drone/thermal/hotspots/branden),
  fire_new/lost/reacquired/archived en flight_end. Nieuwe vlucht sluit af en
  opent een nieuw bestand; `GET /api/flights` en `/api/flights/<naam>` geven
  de bestanden terug. `--log-dir` kiest de map.
- Header: alleen SAURON, verbonden/niet verbonden (op basis van last_update)
  en de nieuwe-vlucht-knop die state + tracker reset.
- Server bindt op 0.0.0.0:8000, anders kan de ESP32 (WiFi-AP) de laptop niet
  bereiken. `--host 127.0.0.1` houdt hem lokaal.
- Versheid is expliciet: State.last_update (epoch) + parallelle log_times; de
  UI toont live/stale in plaats van oude waarden als actueel te presenteren.
- AGL <= 0: brand wel melden, geen coördinaten verzinnen, waarschuwing tonen.
  Nooit een 400/500 door een ontbrekende locatie.
- Framevalidatie: alleen eindige floats. NaN/inf/tekst geeft HTTP 400  in plaats van stil "geen brand".
- Dode pixels / I2C-uitschieters: waarden buiten `valid_temp_min_c`..
  `valid_temp_max_c` (-20..600 C) worden door de mediaan van het frame
  vervangen, vóór blobdetectie én vóór `/api/frame`. Reden: de MLX90640
  heeft altijd een paar dode pixels en een mislukte read geeft -273 of
  1000+. Zonder klep wordt zo'n cel een brand met coördinaten, en schaalt
  het canvas op 1200 C (rest van het veld lijkt ijs). Getest: 3 naast
  elkaar liggende kapotte cellen gaven eerst een brand, nu niets.
- Locatie is een voorrecht: alleen bij `fix >= 2` (3D), een geldige
  dronepositie (niet 0,0 / binnen -90..90 en -180..180) en bekende
  hoogte. Anders: brand wel melden, coördinaten None + uitleg in
  `location_warning` en het logboek. Een kapot GPS-pakket mag nooit de
  hele frame kosten.
- Ingest is tolerant voor de firmware van de teamgenoot: aliassen
  (`temps`/`frame`, `heading`/`yaw`, `alt`/`alt_msl`, `latitude`/
  `longitude`), genest 24x32-frame en `gps_alt_launch` die maar één keer
  per vlucht gestuurd hoeft te worden (laptop onthoudt hem). Afgewezen
  POSTs staan in het logboek (eerste 3 altijd, daarna max 1 per 10 s):
  zonder dat is een verkeerd contract onzichtbaar in het veld.
- `--capture` bewaart ruwe frames in het vluchtbestand; `python3 -m
  sauron.replay <bestand>` hertunet drempels offline op echte velddata en
  telt pixels buiten het geldige bereik.

