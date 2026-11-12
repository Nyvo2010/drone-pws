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

## Firmware van de drone (bron: `Info from esp PWS (temporary)/`)

Het bord **POST niets**; het serveert GET-endpoints. De laptop moet dus
pollen, anders blijft het thermische canvas leeg.

- `:80/api/data` — `{"thermal_available":bool,"frame":[768]|null,
  "thermal":{"min_c","max_c","hotspot":{"x","y"}},"drone":{...}}`.
  Het frame wordt elke 62 ms (16 Hz, `SAURON_READ_INTERVAL_MS`) herbouwd;
  dode pixels zijn JSON-null. Zonder vers frame (< 1 s) geeft het bord
  `{"frame":null,"thermal_available":false}` — zónder `drone`-blok.
  `drone` verschijnt alleen bij een geldige positie.
- `:80/api/gps` — `{"data_seen","location_valid","lat","lon","alt_msl",
  "heading_deg","speed_mps","fix","sats","hdop"}`, met nulls zonder fix.
- `:80/api/status` — wifi/camera/thermal/gps/stream-tellers.
- `:80/capture` — één JPEG; `:81/stream` — MJPEG met Content-Length per frame.
- **fixType is UBX NAV-PVT** (3 = 3D, 2 = 2D), niet de NMEA-schaal van het
  dashboard. `esp32.normaliseer_fix()` rekent om; anders zou een 2D-fix
  als 3D doorgaan en met een verzonnen AGL coördinaten geven.
- `sauronSetLaunchMsl()` wordt nooit aangeroepen, dus `gps_alt_launch` komt
  nooit mee. De laptop zet de eerste bruikbare GPS-hoogte als lanceerpunt
  (of `--launch-alt` voor een exacte AGL).
- De JSON-buffer wordt in `loop()` herschreven terwijl de http-taak hem
  verstuurt: soms komt er een half antwoord. De poller vraagt dan binnen
  100 ms opnieuw in plaats van een halve interval te verliezen.
- Het bord is AP-only (`WiFi.softAP`, `BosbrandDrone`), dus de laptop moet
  in dat netwerk zitten om iets te kunnen ontvangen.

## Detectie herbouwd + lokale logging (11 nov)

Aanleiding: in `logs/flight-20261030-135142.jsonl` staat een frame met
mediaan 486 C en 137 "branden"; losse 3-pixelclusters van 565 C kwamen als
brand door. In het veld werd een zonverwarmde steen (43 C bij 26 C
omgeving) gemeld. De oude regel (omgeving + 10 C, absoluut 40 C) keurt
alles goed wat warmer is dan een schaduwplek.

- Classificatie is tweestandig: **brand** = >= 90 C EN >= 45 C boven de
  mediaan; **verdacht** = >= 60 C EN >= 30 C. Zonverwarmde stenen,
  dakpannen en asfalt halen 55-70 C en vallen dus af. Een vuur op 15 m
  AGL leest honderden graden in de heetste pixel (1 pixel is daar ~1,3 x
  1,0 m grond).
- `valid_temp_max_c` = 350: de sensor is gespecificeerd tot 300 C, alles
  daarboven is een leesfout en wordt door de mediaan vervangen.
- Frame-plausibiliteit: mediaan buiten -15..70 C of meer dan 15% van de
  pixels op de sensorgrens => `sensor_warning`, geen branden. Hotspots
  blijven zichtbaar als diagnose, zodat je ziet wat de sensor zag.
- Tijdsconsistentie: een track is pas "bevestigd" na
  `confirm_observations` (2) metingen; daarvoor staat hij als "verdacht"
  in de UI (amber stippellijn op het canvas). `n_fires` telt alleen
  bevestigde tracks, `n_suspects` de rest.
- Frames hebben een volgnummer (`frame_seq`) + tijd. `/api/frame` geeft
  `seq` en `t` mee; de UI tekent alleen een écht nieuw frame en toont de
  leeftijd van het beeld in de paneelkop (rood na 2,5 s).
- Logging is lokaal en volledig: `logs/dashboard-YYYYMMDD.log` bevat
  elke UI-logregel, de start, camera-opzet, linkstatistieken, fouten en
  onafgevangen exceptions (ook uit threads). Het vluchtbestand heeft per
  ingest `seq`, `frame_time`, `link` (latentie/missers) en `esp32`
  (`thermal_available`, min/max/hotspot, `/api/gps`). `--capture` bewaart
  de ruwe 768 waarden; `--capture-rgb SEC` bewaart JPEG's in `logs/rgb/`.
- Verbinding: `Esp32` houdt de HTTP-verbinding open (keep-alive) en
  probeert een mislukte hergebruikte verbinding één keer opnieuw. De
  poll-lus heeft een vaste cadans, vraagt een half antwoord meteen
  opnieuw, heeft backoff tot 2 s en logt bij 3 missers de echte oorzaak
  via `esp32.diagnose` (timeout / weigert / hangt).
- Camera: bij de stock CameraWebServer worden 480x320 en kwaliteit 10
  automatisch gezet en teruggelezen (`--camera-size`, `--camera-quality`,
  `--no-camera-setup`). De eigen firmware heeft geen `/status` of
  `/control`; dat wordt één keer gelogd en overgeslagen.
- Bug gevonden en gerepareerd: het veld `nmea` in `/api/ingest` werd nooit
  geparseerd, waardoor de gedocumenteerde GPS-route via de firmware dood
  was. Nu vult `gps_nmea.parse_nmea_block` lat/lon/hoogte/fix/sats/hdop/
  koers aan; GGA-kwaliteit 1 wordt dashboardschaal 2 (3D).
- Starten (vanaf de repo-root): `python3 dashboard.py` (echt, pollt
  `http://192.168.4.1`), `python3 dashboard.py --demo` (zonder hardware),
  `python3 selftest.py` (keten + bord controleren).

## Velddata 11 nov 14:07-14:10: waar de brandgrens echt ligt

Drie vluchten met de drone ~1 m van een echte brand
(`logs/flight-20261111-140707.jsonl`, `-140920`, `-141013`). Wat er in de
logs staat:

- **De brand leest geen honderden graden.** Heetste pixel per frame:
  49-116 C in vlucht 1 (ambient 10 C), 49-89.4 C in vlucht 2 (ambient 10 C,
  34 frames tussen 70 en 89 C), en in vlucht 3 niets boven 29 C (brand niet
  in beeld; geen drempelprobleem). Met `fire_min_abs_c = 90` zat de grens
  midden in de verdeling van een echt vuur: vlucht 2 gaf 47x "verdacht" en
  0x brand, vlucht 1 gaf 2 brandframes die nooit bevestigd werden.
- **De relatieve sprong is de betrouwbare grootheid:** 44-105 C boven de
  mediaan, terwijl een zonverwarmde steen 17 C en een warme dakpan 39 C
  haalt. Daarom is +60 C boven de omgeving nu de HOOFDREGEL voor "brand",
  niet een vaste temperatuur. Een vaste grens (90 C) is fysisch fout: de
  absolute waarde zakt met de hoogte (de vlam vult minder dan een pixel),
  met rook en met een warme luchtlaag, terwijl de sprong blijft. Een
  vlam die één pixel vult en 115 C leest in een veld van 12 C is een
  brand; een enkele cel die 25 C boven de omgeving zit is ruis. De
  absolute weg (>= 90 C EN +45 C) bestaat nog als tweede route voor een
  vlam die de pixel vult, niet als voorwaarde.
- **Het heetste frame werd weggepoetst.** Frame seq 109 had `max_c` 640.3 C
  (heter dan de sensor kan uitdrukken) en ons resultaat was 0 hotspots,
  terwijl het bord zelf `fire: true` meldde. Oorzaak: `valid_temp_max_c`
  (350 C) verving elke cel daarboven door de mediaan. Nu wordt een
  aaneengesloten gebied van >= 6 cellen boven de grens op 350 C geklemd en
  telt het als heet voorwerp; losse 3-pixelclusters (30 okt, 565 C) blijven
  ruis en worden nog steeds vervangen.
- **Weergave was de andere helft van het probleem.** Het canvas gebruikte
  percentiel-autogain (p2..p98): de bovenkant lag altijd net boven het veld,
  dus elke hete pixel klipte op rood en 80 C leek identiek aan 130 C. Nu een
  vaste schaal op absolute temperatuur (onderkant mee met de omgeving,
  harde overgang bij 90 C, wit boven 300 C) met een legenda onder het beeld.
- **Nog open:** de 1 m-logs zijn zonder `--capture` gemaakt, dus de ruwe
  frames ontbreken. Voor de volgende meting `python3 dashboard.py --capture`
  gebruiken, dan kan `sauron.replay` de drempels op echte frames hertunen
  (en is het aantal cellen boven de sensorgrens per frame te zien).

## Zwakke ESP32-link: wat de software dan doet (11 nov)

De verbinding is in het veld niet constant. De regel is: **liever een gat
in het beeld dan een verkeerde melding**.

- **Trage sensorread ≠ dode link.** Verbinden heeft een korte timeout
  (1,5 s), lezen een ruime (4 s). Met één gedeelde timeout werden frames
  weggegooid die er wel waren (de ESP32 doet MLX90640-reads en JPEG-encodes
  in dezelfde loop).
- **Afgekapt frame = gemiste poll.** `parse_data` eist precies 768
  waarden; een half antwoord levert `None` en de lus vraagt het meteen
  opnieuw (50 ms), in plaats van een ingest-afwijzing te loggen.
- **Oude positie geeft geen coördinaten.** `/api/gps` komt op 1 Hz; valt
  die weg, dan blijft het warmtebeeld doorkomen. Na
  `max_position_age_s` (3 s) meldt de brand zich zonder coördinaten met
  "positie is N s oud"; de laatste positie blijft zichtbaar met leeftijd
  (`drone.gps_age_s`, in de UI "N s oud").
- **Verse wint van oude.** Een `drone`-blok in `/api/data` is per frame
  vers en wint daarom van de 1 Hz-cache van `/api/gps`.
- **Identiek frame is geen meting.** Een bevroren sensorread of een
  dubbel afgeleverd antwoord mag een brand niet bevestigen: exact dezelfde
  768 waarden verhogen `observations` niet (het frame telt wel voor de
  weergave en krijgt een `seq`). In het logboek: "identiek frame (N×)".
- **Diagnose blokkeert niet meer.** Bij de derde misser draait
  `esp32.diagnose` op een eigen thread en zonder het requestslot, zodat
  het pollen doorgaat op het moment dat herstel telt.
- **Zichtbaarheid.** `link` in `/api/state` bevat `ok_pct` (aandeel goede
  polls van de laatste 60), `latency_ms` en `misses`; de UI toont ze als
  "verbinding" in de telemetrie (amber onder 80%).
- **Bug gefixt:** de 30-seconden-linkregel in `esp32_loop` verwees naar
  `latentties` (typefout) en zou na 30 s de poll-thread met een NameError
  hebben laten stoppen — precies tijdens een vlucht.

## Live link-check op de drone (11 nov)

Gemeten vanaf de laptop in het AP `BosbrandDrone` (en0 192.168.4.3), met
`esp32.Esp32` (keep-alive) en een eigen socket voor :81.

- **WiFi is niet het probleem:** RSSI -38 dBm, 99%, 1 client, `quality`
  `excellent`.
- **`/api/data` is snel:** 20 polls op 4 Hz → mediaan 11 ms (min 9, max
  92). De JSON is 40 bytes zolang er geen frame is.
- **8 Hz pollen is géén optie.** Na een reeks requests op 125 ms
  antwoordde het bord niet meer (elke poll 2,5 s timeout) en daarna was
  de AP helemaal weg: geen ARP-entry, `en0` terug op 192.168.2.69.
  De webserver van de ESP32 is single-task; de bestaande 4 Hz
  (`poll_interval_s = 0.25`) is wat veilig is. **Laat die drempel staan.**
- **Warmtecamera levert geen frames:** `/api/status` → `thermal:
  {"available": true, "status": "mlx90640_frame_error", "frame_errors":
  256}` (oplopend), `/api/data` → `{"frame": null,
  "thermal_available": false}`. Dat is de sensor/read, niet de laptop.
- **GPS-UART is stil, niet "geen fix":** `ubx_detected: true`,
  `ubx_messages: 815`, `checksum_failures: 0`, `baud: 57600`, maar
  `bytes_seen` bleef 10 s lang exact 93420 terwijl `fix_type: 0` en
  `satellites: 0`. Een ontvanger zonder zicht op de lucht levert nog
  steeds NAV-PVT (met fix 0); nul bytes betekent stroom/kabel. Doordat
  er 0 checksumfouten waren stond de baud goed — dit is geen
  baudprobleem, dus de auto-baud in de firmware hoefde niet te wijzigen.
- **De geflashte firmware is nieuwer dan de snapshot in de repo:**
  `/capture`, `/control` en `/status` geven 404; `/api/status` heeft
  extra velden (`frames_received`, `current_fps`, `jpeg_quality`,
  `average_fps`) die in `CameraWebServer_integrated.ino` niet staan. Ga
  voor wat het bord doet uit van de firmware op het bord, niet van die
  kopie.
- **Stream:** `/api/status` meldde 19 fps, ~1,45 kB/frame en 47 ms
  capture per frame. Een tweede verbinding op :81 kwam niet tot stand
  terwijl de tellers opliepen — de firmware heeft één stream-slot, dus
  een open browser-tab concurreert met `--capture-rgb`.

Gevolg voor de laptop (aangepast):

- `App.note_link()` + `esp32.gps_velden()`: zonder warmtebeeld blijven
  link, positie, fix en sats zichtbaar; er wordt geen frame verzonnen
  (`/api/frame` blijft leeg). Daarvoor zei het dashboard "niet
  verbonden" terwijl WiFi en GPS werkten — precies verkeerd om.
- `dashboard.py` logt één keer (en bij herstel) een stille GPS-UART en
  een warmtecamera die geen frames levert.
- De UI pollt `/api/state` op 300 ms i.p.v. 1 s, zodat telemetrie, GPS
  en waarschuwingen niet een seconde achterlopen; branden en logboek
  blijven op ~1 s om DOM-werk en knipperen te voorkomen.
- `python3 selftest.py --esp32-url http://192.168.4.1` meet nu elk
  signaal apart: latentie (mediaan/p95/max), warmtebeeld, GPS-bytes per
  seconde, stream-fps/kB/s en RSSI.

### Naschrift: het bord herstart (zelfde dag, tweede verbinding)

Na een power-cycle bleek de "stille GPS" geen stille GPS: het bord
herstart. Bewijs uit `/api/status`: `stream.last_frame_at_ms` (= millis,
 dus uptime) sprong terug van 120682 naar 163, en `bytes_seen`,
`ubx_messages` en `frames_sent` begonnen weer bij 0.

Per boot verschilt de toestand, en dat is de echte aanwijzing:

| boot | thermal | gps bytes | gps baud | ubx |
|---|---|---|---|---|
| 1 | ok, frames | 11001 | 57600 | 73, 0 cs-fouten |
| 2 | `mlx90640_frame_error` | 0 | 115200 | 0 |
| 3 | `mlx90640_initialization_error` | 10 | 57600 | 0 |

Een sensor die per boot van "ok" naar "initialization_error" wisselt en
een UART die per boot 0, 10 of 11001 bytes ziet: dat is geen parser- of
baudprobleem maar een voeding/bedrading die op de rand zit. De RGB-camera
(19 fps, ~47 ms capture) en de WiFi-AP vragen samen piekstroom; de GPS en
de MLX90640 hangen op dezelfde 5V/3V3-rail. Wat je dan ziet is precies
dit: tellers die bevriezen (bord valt weg), een AP die verdwijnt, en na
een reset weer vanaf 0.

Wat je hieraan vanaf de laptop kunt doen (gedaan):

- `_signaal_waarschuwing` in `dashboard.py` herkent een uptime die terug
  springt en logt "ESP32 herstart", en zet de GPS/thermal-waarschuwingen
  weer scherp. Zonder dat las je een reset als "GPS stil".
- `test_link` meldt het als het bord korter dan 60 s op is.

Wat je fysiek moet nalopen: aparte 5V-voeding (of dikke BEC) voor
ESP32+camera's, gemeenschappelijke GND, en de GPS-TX op GPIO45 met een
korte, vastgezette draad. Pas daarna is een fix binnen enkele minuten
buiten te verwachten; de baud hoeft niet aangepast te worden (0
checksumfouten bij 57600).

## Deep dive: waarom RGB wegvalt en een reset nodig is

Gevraagd: "soms ontvangt de verbinding na een tijdje geen RGB meer en
moeten we blijven resetten". Lees dit samen met `CameraWebServer_
integrated.ino` (regels ~345-400 `streamHandler`, ~543 `httpd_config`,
~695-770 `loop()`) en `sauron_poster.h` (~505-540 `sauronLoop`).

### 1. De streamhandler is één eeuwige lus per verbinding

```cpp
while (true) { frame = esp_camera_fb_get(); ... httpd_resp_send_chunk(...); }
```

Er zit **geen** controle op de client in: geen `httpd_req_to_sockfd()`,
geen tijdslimiet, geen `if (!client) break`. De handler stopt pas als een
`send_chunk` een fout teruggeeft, en dat duurt met `send_wait_timeout = 1`
tot een seconde per frame. Zolang die lus loopt, bezet hij één socket van
de httpd op poort 81.

### 2. Zeven sockets per poort, en de oudste wordt opgeofferd

`config` komt uit `HTTPD_DEFAULT_CONFIG()`: `max_open_sockets = 7`,
en `lru_purge_enable = true` staat expliciet aan. Zodra de browser (of
onze eigen reconnect-lus) meer dan zeven verbindingen op :81 heeft
gehad — en een halfopen verbinding blijft staan tot de handler hem
opruimt — **purget de server de oudste socket, en dat is precies de
stream die je aan het kijken bent.** Symptoom: beeld stopt plots, de
handler blijft hangen in `esp_camera_fb_get()` (framebuffers worden door
meerdere hangende handlers vastgehouden), en nieuwe verbindingen krijgen
de socket nooit meer. Alleen een reset helpt dan, want de sockets en de
framebuffers worden pas bij een reboot vrijgegeven.

Dat verklaart ook de `/api/status`-time-outs die we zagen: het bord was
niet "weg", de httpd had geen socket meer vrij.

**Laptop-kant gedempt (gedaan):** de UI probeerde een dode stream elke
seconde opnieuw. Nu met backoff (1 s → 2 → 4 → ... max 15 s), geen
herverbindingen terwijl het tabblad verborgen is, en een verse stream
zodra je terugkomt. Dat is de reden dat het vroeger sneller doodliep:
elke mislukte poging kostte het bord een socket.

### 3. De GPS wordt uitgehongerd door de thermische read

`loop()` doet `sauronLoop()` (synchrone `MLX90640_GetFrameData` op I2C)
en **daarna** `while (gpsSerial.available())`. Als de MLX90640 hapert,
blokkeert die I2C-read honderden ms (retry-lus in
`MLX90640_I2C_Driver.cpp`), en staat de UART-FIFO van 256 byte vol:

| baud | bytes per 256-byte FIFO |
|---|---|
| 9600 | ~270 ms |
| 38400 | ~67 ms |
| 57600 | ~44 ms |

Elke blokkade langer dan die tijd gooit GPS-bytes weg. Een UBX-bericht
is pas geldig als het compleet is, dus je houdt `ubx_messages` laag,
`fix 0` en `satellites 0` over — precies wat we meten. De enkele keren
dat de sensor wél meteen een fout teruggeeft (vroege `return`) loopt de
GPS wél door; vandaar het wisselende beeld per boot.

Erger: staat de sensor helemaal niet klaar (`initialization_error`), dan
roept `sauronLoop()` elke 5 s `sauronBegin()` opnieuw aan, en die doet
I2C-init **plus** UDP-discovery met `delay(5)`-lussen (3 × 300 ms). Ook
dat blokkeert `loop()` en dus de GPS-UART.

### 4. Wat er in de firmware moet gebeuren (kan vanaf hier niet flashen)

1. `streamHandler`: na elke `send_chunk` controleren of de socket nog
   bestaat en de lus na bv. 30 s zonder succes afbreken; `lru_purge_enable
   = false` en `max_open_sockets = 4` op de stream-server.
2. GPS niet in `loop()` naast de I2C-read: eigen taak (`xTaskCreate`,
   prioriteit boven de thermische read) of een `loop()` die alleen de
   UART leegt en de thermische read in een aparte taak zet.
3. `sauronBegin()` nooit vanuit `loop()`: een state machine die per
   iteratie één stap doet, zonder `delay`-lussen.
4. GPS-RX van **GPIO45** af: dat is op de ESP32-S3 een strapping-pin
   (VDD_SPI). Een pin die bij het opstarten een functie heeft en daarna
   als UART-RX moet dienen, geeft precies dit soort wisselende bytes.
5. `gpsSerial` met een grotere RX-buffer (`setRxBufferSize(1024)` vóór
   `begin()`), zodat een korte blokkade geen bytes meer kost.

Zolang er niet geflasht kan worden: de GPS blijft onbetrouwbaar en de
stream blijft af en toe een reset nodig hebben. Wat de laptop kan doen
is het gedrag eerlijk tonen (herstart, stille UART, offline) in plaats
van "geen data" — dat is nu gedaan.


## De echte firmware (GitHub, 11 nov)

Bron: `github.com/CasperBoi14/CameraWebServer_integrated` —
`CameraWebServer_integrated.ino` (960 regels), `sauron_poster.h` (744),
`elst_map.h`. De kopie in `firmware/` is een oudere schets; deze repo is wat
er op het bord staat.

- **:80** (`/`, `/api/data`, `/api/gps`, `/api/status`) en **:81** (`/stream`)
  zijn twee `httpd`-instanties met dezelfde `httpd_config_t`:
  `max_uri_handlers=16`, `stack_size=8192`, `send_wait_timeout=1`,
  `recv_wait_timeout=1`, `lru_purge_enable=true`, `max_open_sockets` =
  IDF-default 7. Poort 81 heeft `ctrl_port` 32769.
- `streamHandler` is een `while(true)` zonder client-check. Hij stopt alleen bij
  een send-fout of als één frame `>= STREAM_SEND_SLOW_US` (150 ms) kost; dan
  `return ESP_FAIL` en sluit de firmware de verbinding zelf. De eigen pagina
  herverbindt met 100 → 500 ms backoff.
- De stream is vast QQVGA (160x120), JPEG-kwaliteit 40, `CAMERA_GRAB_LATEST`,
  `fb_count=2`, ~19 fps. Resolutie/kwaliteit op afstand instellen kan niet.
- `/api/data` = `sauronLaatsteJson()`, alleen als het frame `< 1000 ms` oud is;
  anders de letterlijke string `{"frame":null,"thermal_available":false}` —
  **zonder** `drone`-blok. GPS komt dus nooit via `/api/data` als de MLX90640
  stuk is; daarom pollt het dashboard `/api/gps` apart en gebruikt het
  `note_link` als er geen frame is.
- `/api/gps` = `sauronLaatsteGpsJson()`: `fresh` = bytes gezien én laatste
  update `<= 2000 ms`. Niet vers → `fix:-1, sats:-1`; vers zonder geldige
  positie → `fix:0, sats:-1`; `location_valid` = vers én lat/lon eindig.
- `/api/status` `gps.fix_type`/`satellites` zijn de **ruwe NAV-PVT-waarden**:
  `hasFix = (flags & 0x01) && fixType >= 2`. Live: `fix_type:3, satellites:4,
  location_valid:false` (3D-fixType zonder gnssFixOK). Daarom neemt
  `esp32.gps_aanvullen` de fix alleen over bij `location_valid`, en sats altijd.
- De .ino geeft TinyGPS voorrang: is `gps.location.isValid()`, dan gaat
  hardcoded `fix = 3` naar de poster; anders de UBX-`fixType`; anders 0.
- MLX90640 leest op 62 ms (16 Hz, `MLX90640_16_HZ`). De poster POST hooguit
  1×/s naar de laptop via UDP-ontdekking op poort 8001 ("SAURON?"); onze server
  luistert daar niet op — wij pollen, dus dat is geen gemis.
- `/status`, `/control` en `/capture` bestaan **niet** in deze build. Alleen de
  stock CameraWebServer heeft die; camera-instellingen op afstand zijn er niet.
- `sauronBegin()` probeert elke 5 s opnieuw en scant daarbij alle 127
  I2C-adressen met `Wire.setTimeOut(100)` — ca. 13 s blokkade per ronde. Dat
  verklaart een deel van de stiltes op `/api/data` zolang de MLX90640 niet
  gevonden wordt.
- De ingebouwde pagina op `/` zet zelf ook `:81/stream` op. Wie die pagina in
  een andere tab open heeft, bezet het enige stream-slot.

## Weergave en detectie (11 nov, na de firmware-analyse)

- **Warmtebeeld staat horizontaal gespiegeld**, en die flip gebeurt op één
  plek: `Config.mirror_frame_x` + `esp32.spiegel_frame_x()` in de poll-lus,
  vóór `ingest_body`. Beeld, hotspot-kaders, coördinaten en het vluchtbestand
  gebruiken daarna dezelfde oriëntatie. Eerder stond de spiegel alleen in de
  UI (`spiegelX` in `drawThermal`); dat was fout, want dan wees een hotspot in
  beeld de andere kant op dan de berekende `hotspot_lon`. Wat fysiek links is,
  blijft een veldcheck: één warmtebron in een hoek en kijken of kader en kaart
  dezelfde kant op wijzen (`mirror_frame_x` / `row0_is_forward` zijn de knoppen).
- **Vastgelopen sensor**: een identiek frame telt niet als nieuwe meting
  (`server.App.ingest`). Het logboek meldt dat nu hooguit één keer per 30 s
  (daarna bij 20/100/500) en vanaf 10 identieke frames verschijnt de
  waarschuwing "warmtecamera levert een vastgelopen frame (N× identiek)".
  Zo kan een bevroren sensor nooit een brand bevestigen én ziet de operator
  dat het beeld stilstaat.
- **Detectie gecontroleerd met realistisch bereik**: veld 27 C met 2x2 cellen
  op 95 C -> `fire` (delta 68 C, area 4); dezelfde vlek op 65 C -> `suspect`.
  Op een echt frame van dit bord: omgeving 24,9 C, drempel 36,9 C, heetste cel
  34,7 C -> 0 hotspots, 0 branden (correct voor een koude ruimte).
- De MLX90640-status wisselt per boot/ronde tussen `ok`,
  `mlx90640_initialization_error`, `mlx90640_configuration_error` en
  `mlx90640_frame_error`. Alleen bij `ok` komen er frames; de rest is
  bedrading/voeding van de sensor, niet de laptop.

## Hoofdtest 11 nov (vlucht 15:26-15:47)

Dit was de **hoofdtest** van de hele keten (drone + ESP32 + dashboard), niet
weer een drempelproef. Vluchtbestand: `logs/flight-20261111-152638.jsonl`.
De laatste 20 minuten (15:40 tot de uitdraai) staan leesbaar in
`logs/main-test-20261111-1540.txt`; de ruwe JSONL blijft de bron. In die
uitdraai zijn reeksen identieke "LET OP"-regels samengevat, al het andere
staat er volledig in.

- **Detecties:** B1-B3 om 15:35:53 (328,7 / 185,0 / 79,3 C, elk 1 meting,
dus verdacht en nooit bevestigd) en B4/B5 om 15:44:52-15:44:57 (70-81 C,
+62 tot +74 C boven de omgeving, bevestigd na 2 metingen, 6-10
waarnemingen). Alle vijf zonder coördinaten: de AGL was 0 tot -6 m, dus
"drone niet boven lanceerpunt".
- **Einde van de run:** geen brand maar de link. Om 15:47:21 "geen data van
de drone", om 15:47:36 "ESP32 antwoordt niet", daarna alleen nog mislukte
polls (480 op rij om 16:01). Er is **geen `flight_end`** geschreven: het
dashboard is gestopt terwijl de vlucht open stond, dus het bestand eindigt
met een gewone logregel.
- **ESP32 herstartte drie keer** tijdens de run (15:34:06, 15:42:34,
15:44:40; uptime terug naar 14-20 s) en de warmtecamera wisselde tussen
`ok`, `mlx90640_frame_error` en `mlx90640_not_found`. Zelfde
voeding/brownout-beeld als eerder op 11 nov.- **Les:** een bevestigde brand met AGL <= 0 is een detectie zonder
  bewijswaarde (grondvlek). Voor de volgende run: eerst boven 5 m AGL
  klimmen voordat een meting als brand telt, en `--capture` aanzetten zodat
  de drempels achteraf op echte frames te hertunen zijn.

## Vuur op hoogte: lokale vergelijking i.p.v. een vaste drempel (11 nov)

Aanleiding: in `flight-20261111-145024.jsonl` en `-152638.jsonl` stond
een echte brand minutenlang in beeld zonder als brand te gelden. Wat de
logs precies laten zien:

- **14:50 (vuur op ~13 m AGL):** van 14:54:27 tot 14:54:52 stond de vlam
  op 45,4 / 55,1 / 66,6 C (area 4-11) met een omgeving van 7 C, dus +38
  tot +59 C. Dat is 25 s lang "verdacht" geweest; pas op 70-82 C
  (+62..+75) werd het "brand", en drie frames later was hij uit beeld.
- **15:26 (hoger):** op 15:35:53 kwam dezelfde vlam binnen als drie
  losse cellen van 328,7 / 185,0 / 79,3 C op (4,7), (8,7) en (6,7) -
  elk area 1, met koude cellen ertussen. Drie tracks, elk na één frame
  weg, dus nooit bevestigd. Om 15:44 (lager, dichterbij) werd het
  70-81 C met area 6-15 en kwam er wél bevestiging.
- **Geen coördinaten bij alle vijf:** AGL was 0 tot -6 m. De firmware
  stuurde geen lanceerhoogte; de laptop pakte de eerste 3D-fix (3,9 m
  MSL) als lanceerpunt, terwijl de GPS-hoogte daarna tussen -2,5 en
  +6,3 m bewoog. Een ruizige referentie van één sample kostte dus elke
  locatie.

Wat er nu anders is:

- **Lokale ring** (`thermal.local_background`): elke blob krijgt
  `local_bg`, `local_delta` en `local_sigma` uit de ring cellen direct om
  hem heen (1 cel buffer, ring 4 cellen). De vergelijking met de grond
  naast de vlam blijft kloppen als de vlam kleiner wordt; de mediaan van
  het hele frame deed dat niet.
- **Derde brandroute** (`classify`): lokaal >= 45 C EN absoluut >= 50 C
  EN (vanaf 3 cellen) een hete kern van >= 6 C boven het blobgemiddelde.
  De twee oude routes (+60 C globaal, of >= 90 C EN +45 C) blijven staan.
  Een groot zonverwarmd dak heeft een ring die net zo warm is en valt af;
  een zonverwarmde steen is vlak van temperatuur (kerncontrast ~0-3 C) en
  blijft "verdacht".
- **Blob-samenvoeging** (`blob_merge_radius = 1`): koude gaten tot 2
  cellen (rook, één cel net onder de drempel) worden overbrugd voordat
  blobs geteld worden. Eén vlam = één hotspot i.p.v. drie 1-pixel-tracks.
- **AGL-referentie** (`geo.HeightReference`): de grond is de mediaan van
  de laatste 3 GPS-hoogtes, en alleen een LAGERE waarde wint. De AGL zelf
  gebruikt de actuele hoogte (geen klim-vertraging). In de 15:26-situatie
  wordt de grond -2,5 m en heeft een hover op 4 m ineens AGL 6,5 m, dus
  coördinaten.
- **Coördinaten uit het centroid** i.p.v. de heetste cel: de heetste cel
  verspringt bij een vlam meters tussen frames; het centroid is dezelfde
  brand met minder ruis.
- **`Config.heading_offset_deg`**: montage-offset tussen kompas en
  warmtecamera. Nodig omdat de heading in deze logs alle kanten op sprong
  (272, 200, 159, 342, 112, ...) en elke graad fout de hotspot om de
  drone heen draait.

**Openstaand coordinate-probleem (geen softwarefout aan te wijzen):** de
gemeten dronepositie in beide vluchten is ~51.9087 / 5.8280, terwijl het
opgegeven vuur op 51.909771 / 5.827337 ligt: 127 m noord-noordwest. Op
13-14 m AGL ziet de camera hooguit ~20 m radius, dus dat vuur kon
geometrisch niet in beeld zijn. De berekende hotspot lag ~2 m van de
drone (51.908762 / 5.827961), wat past bij "drone hangt boven de bron".
Dus: of de gelogde GPS-positie is fout (bron/antenne/montage), of de
pin is fout. Dat is in het veld te controleren: laat een brand op een
bekende plek staan, vlieg er 10 m naast en kijk of de 127 m verdwijnt.
Het logboek noemt nu bij elke nieuwe brand ook de afstand tot de drone,
zodat zo'n sprong meteen opvalt.
