# TODO

## Lopend: bosbranddetectie laptopkant (onze scope)

- [x] Laag 1: heat point identificatie (MLX90640 32x24, threshold + blobs)
- [x] Laag 2: classificatie mogelijke bosbrand (delta-T, absolute temp, score)
- [x] Locatie: AGL = GPS(nu) - GPS(lancering) + pixel -> lat/lon (camera recht omlaag)
- [x] NMEA-parsing (GGA/RMC) + poortdetectie-hulp
- [x] Demo + 11 tests (alleen stdlib, offline)
- [x] Gedeelde staat (`sauron/state.py`) als enige aanspreekpunt
- [x] Autonomie-stub (`sauron/autonomy.py`, uit; naad ligt klaar voor later)
- [x] Localhost-dashboard (`dashboard.py` + `web/index.html`): live RGB + thermal
      + GPS + branden + logs; batterij/modus als placeholders
- [x] POST /api/ingest als naad voor ESP32-gateway (FP frame + FC GPS via UART4, alles over WiFi)
- [x] FC-status velden (fix, sats, hdop) in State + /api/state
- [x] /api/log endpoint voor frontend-logging (hotspot coords + temps in logboek)
- [x] Frontend: Mozilla Headline + Helvetica, logs met hotspot-coördinaten en temperaturen
- [ ] Veldkalibratie: drempels (threshold 12 C, min-area 3 px) + FOV-check 110x75
- [ ] Seriële poort bepalen zodra FC is aangesloten (`gps_nmea.list_candidate_ports`)
- [ ] ESP32 JSON-formaat + GPS-forwarding afstemmen met teamgenoot (768 floats, rij-majeur, FC via UART4)

## Buiten onze scope (teamgenoot)

- [ ] ESP32-firmware (MLX90640 + OV3660 uitlezen, WiFi-AP)
- [ ] Vluchtbesturing / autonoom vliegen
- [ ] Dashboard / kaartweergave
