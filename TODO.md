# TODO

## Lopend: bosbranddetectie laptopkant (onze scope)

- [x] Laag 1: heat point identificatie (MLX90640 32x24, threshold + blobs)
- [x] Laag 2: classificatie mogelijke bosbrand (delta-T, absolute temp, score)
- [x] Locatie: AGL = GPS(nu) - GPS(lancering) + pixel -> lat/lon (camera recht omlaag)
- [x] NMEA-parsing (GGA/RMC) + poortdetectie-hulp
- [x] Demo + 26 tests (alleen stdlib, offline)
- [x] Gedeelde staat (`sauron/state.py`) als enige aanspreekpunt
- [x] Autonomie-stub (`sauron/autonomy.py`, uit; naad ligt klaar voor later)
- [x] Localhost-dashboard (`dashboard.py` + `web/index.html`): live RGB + thermal
      + GPS + branden + logs; batterij/modus als placeholders
- [x] POST /api/ingest als naad voor ESP32-gateway (FP frame + FC GPS via UART4, alles over WiFi)
- [x] FC-status velden (fix, sats, hdop) in State + /api/state
- [x] Brand-tracking: stabiele ID's, laatste meting, uit/terug in beeld zonder duplicaten
- [x] Vluchtlogging: JSONL per vlucht, alle logs + brandinfo, /api/flights download
- [x] Header: Sauron, verbonden ja/nee, nieuwe-vlucht-knop die alles reset
- [x] Frontend: offline mono-UI, logs met echte tijdstippen, live/stale-indicator,
      brandkaarten met status, laatste meting en coördinaten kopiëren
- [x] Server luistert op 0.0.0.0 zodat de ESP32 de laptop over WiFi kan bereiken
- [x] AGL <= 0: brand melden zonder coördinaten (geen crash/400) + waarschuwing
- [x] Detectie op hoogte: lokale ringvergelijking (+45 C lokaal, >= 50 C
      absoluut, hete kern vanaf 3 cellen) naast +60 C globaal en 90 C EN +45 C;
      koude gaten tot 2 cellen worden samengevoegd tot één hotspot
- [x] AGL robuust: grond = mediaan van de laatste 3 GPS-hoogtes, alleen een
      lagere waarde wint; AGL uit de actuele hoogte (geen klim-vertraging)
- [x] Coördinaten uit het blob-centroid i.p.v. de heetste cel +
      `Config.heading_offset_deg` voor de montage-offset van de camera
- [ ] Veldkalibratie: drempels (`fire_local_delta_c`, `fire_core_contrast_c`)
      + FOV-check 110x75 (na de vlucht: `python3 dashboard.py --capture` +
      `python3 -m sauron.replay <bestand>`)
- [ ] GPS-positie/kompas nalopen: gelogde dronepositie lag 127 m van het
      opgegeven vuur terwijl de hotspot ~2 m van de drone berekend werd;
      op 13 m AGL kan dat vuur niet in beeld zijn geweest. Brand op bekende
      plek, 10 m ernaast hoveren en de afstand in het logboek vergelijken.
- [x] Brandgrens herijkt op velddata 11 nov 14:07-14:10 (1 m van een echte
      brand): de SPRONG boven de omgeving (+60 C) is nu de hoofdregel i.p.v.
      een vaste 90 C, want de brand las 49-116 C en op hoogte vult een vlam
      soms maar 1 pixel; 640 C-gebied boven de sensorgrens wordt geklemd
      i.p.v. weggepoetst; kleurenschaal op absolute temperatuur met legenda
- [x] Dode pixels / I2C-uitschieters filteren (-20..600 C -> mediaan), ook voor het canvas
- [x] Locatie alleen bij fix >= 2, geldige positie en bekende hoogte (anders brand zonder coördinaten)
- [x] Ingest tolerant voor het firmware-contract + afgewezen POSTs in het logboek
- [x] Ruwe frames opnemen (`--capture`) + offline replay om drempels te hertunen
- [x] Realistische drempels: brand = 90 C EN +45 C boven omgeving; steen/asfalt
      (55-70 C) valt af als "verdacht" i.p.v. vals alarm
- [x] Frame-plausibiliteit: mediaan -15..70 C en max 15% verzadigd, anders
      sensorwaarschuwing zonder branden (log 30 okt: mediaan 486 C, 137 "branden")
- [x] Tijdsconsistentie: track pas "bevestigd" na 2 metingen; eenmalige
      uitschieters blijven "verdacht"
- [x] Lokale logging: `logs/dashboard-YYYYMMDD.log` (alle regels, camera, link,
      fouten, excepthooks) + JSONL met `seq`, `frame_time`, `link` en `esp32`-meta
- [x] Keep-alive naar de ESP32, camera-opzet (480x320/kwaliteit 10), backoff en
      diagnose bij wegvallen
- [x] Dashboard tekent alleen nieuwe frames (seq) en toont de leeftijd van het beeld
- [x] `nmea`-veld in /api/ingest wordt nu echt geparseerd (was stil genegeerd)
- [x] Zwakke link: aparte lees-timeout, afgekapt frame = meteen opnieuw vragen,
      oude positie (> 3 s) geeft geen coördinaten, verse /api/data-positie wint
      van de 1 Hz-cache
- [x] Identiek frame telt niet als nieuwe meting (bevroren sensor bevestigt
      geen brand); `duplicate` staat in het vluchtbestand
- [x] Diagnose bij uitval op een eigen thread (blokkeert het pollen niet) en
      linkkwaliteit (`ok_pct`) zichtbaar in de telemetrie
- [x] Dashboard toont link + GPS ook zonder warmtebeeld (`note_link`), zonder
      een frame te verzinnen
- [x] Zelftest meet elk signaal apart: latentie (mediaan/p95/max), warmtebeeld,
      GPS-bytes per seconde, stream-fps/kB/s en RSSI
- [ ] Bord herstart herhaaldelijk (uptime springt terug naar 0, AP verdwijnt,
      thermal per boot ok/`mlx90640_initialization_error`): eigen 5V-voeding of
      dikke BEC voor ESP32 + camera's, gemeenschappelijke GND
- [ ] GPS-UART levert per boot 0/10/11001 bytes (fix 0, 0 sat): GPS-TX op
      GPIO45 en de 5V van de module nalopen; baud hoeft niet anders
      (0 checksumfouten bij 57600)
- [ ] Pollfrequentie niet verhogen: 8 Hz op /api/data legde de webserver van
      de ESP32 plat en daarna verdween de AP (zie KNOWLEDGE.md, 11 nov)
- [ ] Firmware (github.com/CasperBoi14/CameraWebServer_integrated):
      `streamHandler` is een `while(true)` zonder client-check en stopt alleen
      bij een send-fout of als één frame >= 150 ms kost; poort 80 en 81 delen
      één `httpd_config_t` met `lru_purge_enable = true` en het IDF-default
      `max_open_sockets = 7`. Voorstel: socket-check + tijdslimiet,
      `lru_purge_enable = false`, `max_open_sockets = 3`
- [ ] Firmware: `sauronBegin()` scant elke 5 s alle 127 I2C-adressen met
      `Wire.setTimeOut(100)` (ca. 13 s blokkade per ronde) — dat verklaart een
      deel van de stiltes op `/api/data` zolang de MLX90640 niet gevonden wordt
- [ ] Firmware: GPS-UART leegmaken buiten `loop()`/de I2C-read om (eigen taak
      of `setRxBufferSize(1024)`), en GPS-RX van GPIO45 af (strapping-pin)
- [ ] Seriële poort bepalen zodra FC is aangesloten (`gps_nmea.list_candidate_ports`)
- [ ] ESP32 JSON-formaat + GPS-forwarding afstemmen met teamgenoot (768 floats, rij-majeur, FC via UART4)

## Veldtest-checklist (morgen)

- [ ] Laptop verbinden met WiFi-AP `BosbrandDrone` (192.168.4.1)
- [ ] `python3 dashboard.py` starten; LAN-IP uit de startup-regel noteren
- [ ] ESP32 laten POSTen naar `http://<laptop-ip>:8000/api/ingest`
- [ ] Header op `verbonden` controleren (niet verbonden = geen frames meer)
- [ ] RGB-stream `http://192.168.4.1:81/stream` in het dashboard controleren
- [ ] GPS-fix/sats/hdop en AGL 5-30 m controleren
- [ ] Oriëntatie-check: verwarm één hoek van het beeld, hotspot moet in diezelfde hoek staan
      (90 graden gedraaid gemonteerd = alle coördinaten 90 graden fout)
- [ ] Dode-pixel-check: `replay` op een leeg veld, "buiten bereik" moet 0-2 zijn
- [ ] Testbrand/heatgun: hotspot, classificatie, coördinaten en afstand checken
- [ ] Brand even buiten beeld laten vallen: status wordt "uit beeld", geen duplicaat
- [ ] Nieuwe-vlucht-knop testen: reset + nieuw bestand in `logs/`
- [ ] Na de test `logs/flight-*.jsonl` controleren op logs en brandinfo
- [ ] Drempels en FOV noteren die in het veld echt werken

## Buiten onze scope (teamgenoot)

- [ ] ESP32-firmware (MLX90640 + OV3660 uitlezen, WiFi-AP, POST naar /api/ingest)
- [ ] Vluchtbesturing / autonoom vliegen
- [ ] Kaartweergave (Leaflet); het dashboard zelf is onze scope

## Laatste controle (11 nov)

- [ ] Veldcheck oriëntatie: één warmtebron in een hoek → hotspot-kader én
      kaartpunt moeten dezelfde kant op wijzen. Zo niet: `Config.mirror_frame_x`
      of `Config.row0_is_forward` omzetten (instelling, geen codewijziging)
- [ ] `python3 selftest.py` faalt bewust op twee echte punten: GPS-UART levert
      0 bytes (module stil → bedrading/voeding/antenne) en de stream op :81 is
      bezet door een andere client. Beide zijn hardware/clients, geen laptopcode;
      `/capture` en `/control` staan als "niet ondersteund" en tellen niet meer
      als fout
