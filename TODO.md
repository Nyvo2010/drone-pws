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
- [ ] Veldkalibratie: drempels (threshold 12 C, min-area 3 px) + FOV-check 110x75
      (na de vlucht: `python3 dashboard.py --capture` + `python3 -m sauron.replay <bestand>`)
- [x] Dode pixels / I2C-uitschieters filteren (-20..600 C -> mediaan), ook voor het canvas
- [x] Locatie alleen bij fix >= 2, geldige positie en bekende hoogte (anders brand zonder coördinaten)
- [x] Ingest tolerant voor het firmware-contract + afgewezen POSTs in het logboek
- [x] Ruwe frames opnemen (`--capture`) + offline replay om drempels te hertunen
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
