# ESP32 herprogrammeren — thermische camera aan het werk krijgen

**Doel:** de MLX90640 (warmtecamera) wordt uitgelezen en elke seconde verstuurd
naar de dashboard. Daarna zie je het thermische beeld, de warme vlekken én de
branden live in `http://localhost:8000`.

> **Update 20 okt — het bord serveert nu zelf.** De nieuwe firmware draait
> geen stock `CameraWebServer` meer: hij serveert `/capture` (RGB),
> `/api/data` (warmtebeeld + GPS) en `/api/status`. De laptop hoeft dus
> niets te POSTen en er is **geen IP in de firmware** nodig —
> `dashboard.py` pollt `/api/data` één keer per seconde. Wat er nog moet
> gebeuren is alléén dat de MLX90640 een frame gaat leveren
> (`thermal_available:true`); zolang dat `false` is blijft het canvas leeg
> en zegt de header `[~] warmtecamera nog niet klaar`. De rest van dit
> document beschrijft de POST-variant (`sauron_poster.h`) als alternatief.

---

## 0. Het contract van `/api/data` (wat de laptop verwacht)

De laptop pollt `/api/data` één keer per seconde. Alles wat hieronder staat
is optioneel behalve het veld `frame`; onbekende velden negeren we.

```json
{
  "frame": [768 getallen in graden Celsius, rij-majeur, 32 kolommen x 24 rijen],
  "thermal_available": true,
  "gps": {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
          "heading_deg": 90.0, "fix": 3, "sats": 8, "hdop": 0.9},
  "nmea": "$GPGGA,...\r\n$GPRMC,...",
  "gps_alt_launch": 10.0
}
```

- **`frame`** mag een platte lijst van 768 zijn of 24 rijen van 32. Waarden
  moeten **graden Celsius** zijn (ongeveer -20..600). Stuur je ruwe
  sensorwaarden of Kelvin, dan zet de laptop die cellen op de mediaan en
  schrijft hij een waarschuwing in het logboek.
- **`thermal_available`** mag `false` zijn met `frame: null` zolang de
  MLX90640 nog niets heeft. De laptop doet dan niets en wacht gewoon.
- **`gps`** is vrijblijvend: ontbreekt hij, dan komt er een brand zonder
  coördinaten. `fix` gebruikt de schaal 0 = geen, 1 = 2D, 2 = 3D, 3 = RTK;
  alleen bij 2 of hoger rekent de laptop coördinaten uit.
- **`nmea`** is de makkelijkste GPS-route: zet de ruwe zinnen van de GPS
  (G37) erin, dan parseert de laptop ze zelf.
- **Niet blokkeren**: de webserver van de ESP32 is single-task. Een
  `while (!mlx.ready()) delay(10);` of een I2C-read met timeouts in de
  handler laat `/api/data` én `/api/status` hangen terwijl `/capture`
  blijft werken (precies wat we gemeten hebben). Lees de sensor in
  `loop()`/een eigen task, bewaar het laatste frame in een variabele en
  laat de handler alleen dat kopiëren.

---

## 1. Wat is er nu aan de hand (gemeten, 20 oktober)

| Waarneming | Meetresultaat |
|---|---|
| Firmware | **byte-identiek** de stock Arduino `CameraWebServer` (de gepserveerde pagina is gelijk aan `index_ov5640.html` uit de Arduino-bibliotheek) |
| `/thermal`, `/mlx`, `/frame`, `/temps`, `/sensor`, `/info` | **alle 404** — er bestaat geen enkel thermisch endpoint |
| Ingest naar de laptop | **nooit**: `/api/state` → `last_update: None` |
| MLX90640 uitlezen | **geen enkele regel code** die de sensor aanraakt |
| USB-seriepoort op de laptop | **geen** `/dev/cu.usb*` → niet te flashen vanaf deze laptop |
| RGB-camera | werkt wél: `/status`, `/capture`, `/control` (480x320, spiegeling, kwaliteit staan goed) |

**Gevolg in de UI:** de header blijft op `[~] geen warmtdata` staan, het
thermische canvas blijft leeg en er komen géén branden — ook als er echt een
brand is. Dat is géén bug in de laptop: de drone stuurt simpelweg niets.

**Wat al wél klaar is (laptop-kant, getest):**
- `POST /api/ingest` accepteert het frame, vindt branden met GPS-coördinaten en
  schrijft alles weg naar het vluchtbestand (`python3 selftest.py` → 17× ok).
- De laptop **advertiseert zichzelf** via UDP poort 8001: de ESP32 stuurt
  `SAURON?` en krijgt de ingest-URL terug. **Er hoeft dus geen IP in de
  firmware geplakt te worden.**
- Camera-instellingen worden automatisch toegepast (480x320, kwaliteit 10,
  horizontale spiegel aan) zodra de drone bereikbaar is.

---

## 2. Wat er moet veranderen (kort)

1. **Eén bibliotheek** installeren: `Adafruit MLX90640`.
2. **Eén bestand** in de sketch-map leggen: `sauron_poster.h` (ligt in deze map).
3. **Drie regels** toevoegen aan `CameraWebServer.ino`.
4. **Bedrading nakijken**: SCL is verplaatst van **B2 → B40**.
5. **Flashen**.

> Dit bestand is **gecompileerd en geverifieerd** voor esp32 én esp32s3
> (sectie 8); er hoeft dus niets meer geraden te worden.

Geen wijziging aan de camera, het WiFi-punt of de RGB-stream: die blijven
precies zoals ze nu zijn.

---

## 3. Stappen

### Stap 1 — bibliotheek
Arduino IDE → **Schets → Bibliotheek beheren → Bibliotheken beheren** → zoek
`Adafruit MLX90640` → *Installeren*. (Trekt `Adafruit BusIO` automatisch mee.)

### Stap 2 — bestand erbij
`firmware/sauron_poster.h` kopiëren naar de map van de sketch, dus naast
`CameraWebServer.ino`.

### Stap 3 — drie regels in `CameraWebServer.ino`

```cpp
#include "sauron_poster.h"          // bovenaan, bij de andere #includes

void setup() {
  ...bestaande WiFi- en camera-code...
  sauronBegin();                    // NA WiFi.begin(...) / startCameraServer()
  sauronBeginGps();                 // GPS op G37 (optioneel, zie stap 4b)
}

void loop() {
  ...niets weggooien...
  sauronLoop();                     // leest de GPS leeg, stuurt 1 frame/s
}
```

### Stap 4 — bedrading MLX90640 controleren

| MLX90640-pin | ESP32-pen | Let op |
|---|---|---|
| VIN | 3V3 | |
| GND | GND | |
| SDA | **B1** (GPIO1) | blijft zoals het was |
| SCL | **B40** (GPIO40) | **was B2 — hoor nu op B40** |

### Stap 4b — GPS op G37 (TX van de GPS naar GPIO37)

De GPS hangt met zijn **TX aan G37** (GPIO37) van de ESP32, plus **GND** en
de eigen **voeding** van de module (3V3 of 5V — check het bordje).

Belangrijk: **de laptop parst de NMEA, niet de ESP32.** De firmware hoeft
de zinnen alleen maar mee te sturen in het POST-pakket; `sauron_poster.h`
doet dat al. Je hoeft dus niets te interpreteren en er komt geen tweede
parser naast de laptop.

Wat het bestand voor je doet:

```cpp
sauronBeginGps();      // in setup(): Serial2 op GPIO37, 9600 baud
sauronLoop();          // leest Serial2 leeg en zet de laatste GGA+RMC
                       // als "nmea" in elk POST-pakket
```

Let op twee dingen:

- **Niet UART0 (RX0) gebruiken.** Die poort is van de USB-console; een GPS
  op 9600 baud naast de serial-monitor op 115200 geeft aan beide kanten
  onleesbare rommel én kan het flashen verstoren. `sauronBeginGps()`
  gebruikt daarom `Serial2` op GPIO37.
- **Baudrate.** Staat er niets in de serial-monitor, dan zit de module op
  een andere snelheid. In de sketch: `sauronBeginGps(38400);` of
  `sauronBeginGps(115200);` (u-blox M10 staat standaard vaak op 38400).
- **GPIO37 en PSRAM.** Op een ESP32-S3 met *octal* PSRAM zijn GPIO33–37
  bezet. Werkt het bord met OPI-PSRAM, kies dan een vrije pin (bijv.
  GPIO14) via `#define SAURON_GPS_RX 14` vóór de include. Symptoom: geen
  NMEA, terwijl de module wel stroom heeft.

Op de laptop zie je het resultaat meteen: `drone lat/lon/fix/sats` in het
dashboard. Zonder lanceerhoogte komen er nog geen coördinaten bij een
brand — start dan met `python3 dashboard.py --launch-alt 10` (MSL-hoogte
van het veld), of stuur `sauronSetLaunchMsl(...)` mee.

### Stap 5 — flashen
Board-instellingen laten zoals de drone nu al geflasht wordt (115200 is de
standaard-snelheid van het sketch, `Serial.begin(115200)`). Na het flashen de
serial-monitor openen op 115200 — je moet zien:

```
[sauron] MLX90640 initialiseren (SDA=1, SCL=40)...
[sauron] MLX90640 klaar; 1 frame/s naar de dashboard.
[sauron] dashboard niet gevonden (staat hij aan?)   <-- als de laptop nog uit is
```

---

### Voor de test: zorg dat de laptop de drone binnenlaat

Dit is de valkuil waar niemand aan denkt: op de testlaptop **wordt
inkomend verkeer naar het eigen LAN-IP geblokkeerd** (gemeten: een
`curl` naar `http://<laptop-ip>:8000` vanaf de laptop zelf wordt
afgekapt, en zelfs `ping <eigen-ip>` geeft 100% verlies — terwijl
`localhost` gewoon werkt). Ook het dashboard logt dit nu bij het starten:

```
LAN-check MISLUKT: 192.168.2.69 blokkeert inkomende verbindingen (...)
advies: macOS-stealth-mode of een VPN uitzetten voor de veldtest
```

Oorzaken die gevonden zijn op deze laptop: **stealth-mode staat aan** en
er draaien **ProtonVPN + Tailscale**. Wat te doen vóór de vluchttest:

1. **ProtonVPN en Tailscale even afsluiten**.
2. **Stealth-mode uit**: Systeeminstellingen → Netwerk → Firewall →
   Opties → "Stealth-modus" uit.
3. **Bewijs dat het werkt**: open op je **telefoon** (zelfde WiFi)
   `http://<laptop-ip>:8000/api/state` — als die laadt, kan de ESP32 het
   ook.

Zonder dit stuurt de drone frames die nergens aankomen, en dat zie je als
"geen warmtdata" — verwarrend, want de drone doet dan wél zijn werk.

## 4. Het contract (voor wie het wil begrijpen)

De ESP32 POSTt elke seconde naar de URL die hij via UDP heeft gekregen:

```
POST http://<laptop>:8000/api/ingest
Content-Type: application/json

{"frame":[768 temperatuuren in °C, rij-majeur, 32 kolommen x 24 rijen],
 "nmea":"$GPGGA,...,25.0,M,...\r\n$GPRMC,...,084.4,...",
 "gps_alt_launch":10.0}
```

- `nmea` is de **eenvoudigste route**: de ruwe GGA/RMC-zinnen van de GPS.
  De laptop haalt er lat/lon/hoogte/fix/sats/hdop en de koers (heading) uit.
  `sauron_poster.h` vult dit veld automatisch.
- Geparseerde velden mogen ook, en winnen van de NMEA:
  `"drone":{"lat":52.09,"lon":4.31,"alt_msl":25.0,"heading_deg":90.0,
  "fix":3,"sats":12,"hdop":0.9}`.
- De koers komt uit RMC (course over ground). Die is alleen zinvol als de
  drone beweegt; een stilstaande GPS geeft 0 of niets. Voor de
  hotspotlocatie is een kloppende heading wel nodig — vlieg dus niet
  stilhangend als je coördinaten wilt.

- `frame` is het enige verplichte veld. Zonder `drone` krijg je wél een brand,
  maar zonder coördinaten (met een waarschuwing in de UI).
- `gps_alt_launch` (MSL-hoogte van het lanceerpunt) hoeft maar één keer per
  vlucht mee; de laptop onthoudt hem.
- GPS is **optioneel**: `sauronSetGps(lat, lon, altMsl, heading, fix, sats,
  hdop)` en `sauronSetLaunchMsl(altMsl)` bestaan als hooks — zodra de
  GPS-forwarding (UART4) klaar is, één regel toevoegen.
- Antwoord `{"ok":true,"n_fires":0}`; een pakket dat echt niet klopt geeft
  HTTP 400 en komt als `ingest afgewezen: ...` in het logboek.

---

## 5. Controles na het flashen

1. **Serial-monitor**: `[sauron] MLX90640 klaar`.
2. **Dashboard starten**: `python3 dashboard.py` → in het logboek
   `ESP32-ontdekking op udp/8001 -> http://192.168.4.x:8000/api/ingest`.
3. **Verbinding**: de header gaat van `[~] geen warmtdata` naar `[●] verbonden`
   zodra het eerste frame binnen is; het thermische canvas toont kleuren.
4. **Warmteproef**: houd je hand of een föhn onder de sensor → een rode vlek
   in het canvas + eventueel een brandmelding.
5. **Zelftest**: `python3 selftest.py` (checkt laptop + camera, zegt of de
   drone frames stuurt).

---

## 6. Oriëntatiecheck (doen, kost 30 seconden)

Verwarm één hoek van het beeld (bijv. bovenlinks) en kijk waar de marker in
het dashboard staat. Hoort het in dezelfde hoek, dan klopt alles.

Staat het beeld gedraaid of gespiegeld, dan in `sauron_poster.h` zetten:

```cpp
#define SAURON_TRANSPOSE 1    // beeld is 90° gedraaid
#define SAURON_MIRROR_X  1    // beeld is horizontaal gespiegeld
```

---

## 7. Foutentabel

| Wat je ziet | Oorzaak | Oplossing |
|---|---|---|
| `[sauron] MLX90640 NIET gevonden` | bedrading | 3V3/GND, **SDA=B1, SCL=B40** (B2 klopt niet meer) |
| `dashboard niet gevonden` | laptop uit of niet op drone-WiFi | laptop verbinden met `BosbrandDrone`, `python3 dashboard.py` |
| `POST mislukt (HTTP 400)` | contract klopt niet | logboek lezen: `ingest afgewezen: ...` |
| `POST mislukt (HTTP 000)` | laptop weg / IP veranderd | vanzelf opnieuw ontdekt bij de volgende poging |
| Header blijft `[~] geen warmtdata` | er komen geen POSTs aan | serial-monitor kijken, dan `curl http://192.168.4.1/` |
| Geen `drone lat/lon` in het dashboard | geen NMEA, of verkeerde baudrate | `sauronBeginGps(38400);` proberen; G37 + GND + voeding checken |
| Wel positie, geen coördinaten bij een brand | lanceerhoogte ontbreekt | `python3 dashboard.py --launch-alt <meter MSL>` |
| Brand zonder coördinaten | geen GPS in het pakket | `sauronSetGps(...)` aansluiten op de GPS-forwarding |
| Wel vlekken, maar in de verkeerde hoek | pixelvolgorde | hoofdstuk 6 (`SAURON_TRANSPOSE`/`SAURON_MIRROR_X`) |

---

## 8. Gebouwd en geverifieerd op de laptop (20 okt)

Het bestand is niet alleen geschreven maar ook **echt gecompileerd**, met de
Arduino-CLI en de officiële ESP32-bibliotheek (esp32:esp32 v3.3.12 +
Adafruit MLX90640 1.1.2):

| bouw | flash | RAM | uitkomst |
|---|---|---|---|
| `sauron_poster.h` alleen (testschets), esp32s3 | 78% | 22% | ✅ exit 0 |
| `sauron_poster.h` alleen (testschets), esp32 | 81% | 22% | ✅ exit 0 |
| **volledige CameraWebServer-sketch + dit bestand**, esp32s3 | 89% | 29% | ✅ exit 0 |
| **volledige CameraWebServer-sketch + dit bestand**, esp32 | 92% | 30% | ✅ exit 0 |

Onderweg gevonden en al gerepareerd: de Adafruit-enum heet
**`MLX90640_8_HZ`** (niet `MLX90640_REFRESH_8_HZ`) — dat gaf een
compileerfout. Dus: het bouwt schoon op beide borden.

**Let op bij 92%:** er blijft weinig speling over. Als de eigen firmware
nog iets toevoegt en de bouw meldt dat het programma niet past, dan in de
Arduino-IDE bij *Tools → Partition Scheme* **`Huge APP (3MB No OTA)`** kiezen.

## 9. Als flashen nu niet kan

Thermisch blijft dan uit — er is géén omweg (geen netwerkendpoint, geen
USB-seriepoort, de sensor hangt aan de ESP32 en niet aan de laptop). De
overige onderdelen werken ondertussen wel: RGB 480x320 met spiegeling,
camera-instellingen live zichtbaar in het paneel **esp32 / camera**, en de
keten van ingest → brand → vluchtbestand is getest. Zodra er geflasht kan
worden is het met de bovenstaande vijf stappen geregeld.
