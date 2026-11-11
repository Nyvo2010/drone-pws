"""Startpunt dashboard: server + (optioneel) gesimuleerde live-feed.

Veld (echt):   python3 dashboard.py
  -> de laptop pollt de firmware van de drone: GET /api/data (warmtebeeld)
     + GET /api/gps (positie), 4x per seconde. Alle processing draait hier
     op de laptop. POST /api/ingest blijft ook werken (handmatig testen).

Demo (geen hardware):  python3 dashboard.py --demo
  -> achtergrondthread post elke seconde een nep-frame (vlek drijft
     langzaam) + vaste dronepositie. Handig voor UI-check zonder drone.

Open daarna: http://localhost:8000

Logging (alles lokaal, niets naar internet):
- `logs/flight-YYYYMMDD-HHMMSS.jsonl`  elk frame + elke beslissing
  (met --capture ook de ruwe 768 waarden per frame);
- `logs/dashboard-YYYYMMDD.log`        het verhaal van deze sessie:
  start, verbinding, camera, latentie, fouten, elke UI-logregel;
- `logs/rgb/*.jpg`                     alleen met --capture-rgb: foto's
  om achteraf te zien wat de camera zag bij een melding.
"""

import argparse
import json
import logging
import math
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from sauron import applog, esp32
from sauron.config import DEFAULT
from sauron.flightlog import FlightRecorder
from sauron.server import App, run
from sauron.sim import make_frame

LOG = logging.getLogger("sauron.dashboard")

# Vaste demo-positie: 25 m MSL, gelanceerd vanaf 10 m -> AGL 15 m.
DRONE = {"lat": 52.090000, "lon": 4.310000, "alt_msl": 25.0, "heading_deg": 90.0}
ALT_LANCERING = 10.0


def demo_loop(app, interval=1.0):
    """Post elke seconde een frame; de vlek drijft voor 'live' gevoel."""
    t = 0
    app.state.add_log("demo-feed gestart (geen hardware)")
    while True:
        # Vlek beweegt langzaam heen en weer: hotspot-coördinaten veranderen.
        x = 16 + 6 * math.sin(t * 0.3)
        frame = make_frame(vlekken=[(x, 10, 250.0, 2.5)], seed=t)
        app.ingest(frame, DRONE, ALT_LANCERING)
        t += 1
        time.sleep(interval)


def parse_size(tekst):
    """'480x320' -> (480, 320); 'none' -> (None, None); leeg -> None."""
    if not tekst:
        return None
    tekst = str(tekst).strip().lower()
    if tekst in ("none", "off", "uit"):
        return (None, None)
    if "x" not in tekst:
        raise SystemExit("camera-formaat moet er als 480x320 uitzien")
    breedte, hoogte = tekst.split("x", 1)
    return (int(breedte), int(hoogte))


def camera_opzetten(client, size, quality):
    """Zet de camera op de instellingen met het beste beeld per byte.

    Alleen de stock CameraWebServer heeft /status en /control. De eigen
    firmware van de drone serveert die niet (die geeft /api/status) — dan
    slaan we dit stil over: het dashboard moet blijven werken.
    """
    if size is None and quality is None:
        return
    status = client.status()
    if not isinstance(status, dict):
        LOG.info("camera-instellingen overgeslagen: geen /status "
                 "(eigen firmware zonder camera-besturing)")
        return
    breedte, hoogte = size if size else (480, 320)
    rapport = esp32.apply_camera_config(client, breedte, hoogte, quality,
                                        spiegel=None)
    if rapport["gezet"]:
        LOG.info("camera gezet: %s", ", ".join(rapport["gezet"]))
    if rapport["mislukt"]:
        LOG.warning("camera niet volledig gezet: %s",
                    ", ".join(rapport["mislukt"]))
    gelezen = rapport.get("status") or {}
    LOG.info("camera nu: resolutie %s, kwaliteit %s, hmirror %s, vflip %s",
             gelezen.get("resolutie"), gelezen.get("quality"),
             gelezen.get("hmirror"), gelezen.get("vflip"))


def status_melding(client, vorige):
    """Log wifi/camera/thermal-status als die verandert (geen spam).

    /api/status bevat de WiFi-kwaliteit (RSSI van de laptop), het aantal
    streamframes en de warmtecamera-status. Verandert er niets, dan komt
    er ook geen regel: het logbestand blijft leesbaar.
    """
    status = client.api_status()
    if not isinstance(status, dict):
        return vorige
    wifi = status.get("wifi") or {}
    kern = {
        "wifi": wifi.get("quality"),
        "rssi_dbm": wifi.get("rssi_dbm"),
        "clients": wifi.get("clients"),
        "thermal": status.get("thermal"),
        "gps": status.get("gps"),
        "stream_frames": (status.get("stream") or {}).get("frames_sent"),
    }
    if kern != vorige:
        LOG.info("ESP32-status: %s", json.dumps(kern, ensure_ascii=False))
    return kern


def rgb_capture_loop(client, directory, every):
    """Bewaar periodiek een RGB-foto (--capture-rgb SEC)."""
    map_ = Path(directory) / "rgb"
    map_.mkdir(parents=True, exist_ok=True)
    while True:
        time.sleep(every)
        jpeg = client.capture()
        if not jpeg:
            LOG.warning("RGB-foto mislukt (camera bezet of geen antwoord)")
            continue
        pad = map_ / ("rgb-%s.jpg" % datetime.now().strftime("%Y%m%d-%H%M%S"))
        try:
            pad.write_bytes(jpeg)
        except OSError as fout:
            LOG.warning("RGB-foto niet opgeslagen: %s", fout)
            continue
        LOG.info("RGB-foto opgeslagen: %s (%d bytes)", pad.name, len(jpeg))


def _diagnose_log(base_url):
    """Zoek op een eigen thread uit waaróm het bord niet antwoordt."""
    soort, uitleg = esp32.diagnose(base_url, timeout=1.5, use_slot=False)
    LOG.warning("ESP32 niet bereikbaar (%s): %s", soort, uitleg)


def esp32_loop(app, base_url=esp32.DEFAULT_BASE_URL, interval=0.25,
               camera_size=(480, 320), camera_quality=10, setup_camera=True,
               capture_rgb=0.0):
    """Poll /api/data + /api/gps en voer elk frame als ingest uit.

    De firmware van de drone serveert het warmtebeeld als GET; hij POST
    niets. De sensor ververst op 8 Hz (SAURON_READ_INTERVAL_MS = 125),
    dus 4 polls per seconde geven een vloeiend beeld zonder het bord te
    overvragen.

    Wat deze lus doet voor een stabiele verbinding:
    - vaste cadans (rekenen vanaf de vorige deadline, niet vanaf "nu");
    - een half/afgekapt antwoord meteen opnieuw vragen, geen halve
      interval verliezen;
    - bij langer wegblijven een korte backoff (max 2 s), zodat het bord
      niet bestookt wordt en het beeld snel terugkomt;
    - één keer per storing de echte oorzaak loggen (timeout, weigert,
      hangt) met esp32.diagnose;
    - keep-alive-verbindingen (zie esp32.Esp32), zodat niet elke poll een
      nieuwe TCP-handshake kost;
    - lezen met een ruimer timeout dan verbinden: een ESP32 die net een
      sensorread doet is traag, niet dood;
    - een afgekapt of verkeerd frame telt als gemiste poll en wordt meteen
      opnieuw gevraagd;
    - de leeftijd van de positie gaat mee: een oude /api/gps levert geen
      coördinaten meer op in plaats van coördinaten die niet kloppen;
    - de diagnose draait op een eigen thread, zodat het pollen doorgaat
      op het moment dat herstel telt;
    - elke 10 s /api/status, alleen loggen als er iets verandert.
    """
    # Verbinden moet snel zijn (anders is het bord echt weg); lezen mag
    # langer duren, want een ESP32 die net een MLX90640-read of een
    # JPEG-encode doet antwoordt soms pas na een seconde. Met één gedeelde
    # timeout gooide een zwakke link frames weg die er wél waren.
    client = esp32.Esp32(base_url, timeout=1.5, read_timeout=4.0)
    st = app.state
    st.rgb_url = esp32.stream_url(base_url)
    st.add_log("ESP32 pollen op %s" % base_url)

    camera_done = not setup_camera
    vorige_status = None
    gps = None
    gps_tijd = None  # moment waarop /api/gps voor het laatst antwoordde
    teller = 0
    gemist = 0
    gemeld = set()
    volgende = time.monotonic()
    laatste_stat = time.monotonic()
    laatste_diagnose = 0.0
    frames_ok = 0
    frames_fout = 0
    latenties = []
    # Laatste 60 polls: genoeg om een dip te zien zonder dat een slechte
    # minuut het beeld voor de rest van de vlucht bepaalt.
    resultaten = deque(maxlen=60)

    if capture_rgb:
        threading.Thread(target=rgb_capture_loop,
                         args=(client, app.recorder.directory
                               if app.recorder is not None else "logs",
                               capture_rgb),
                         daemon=True).start()

    while True:
        wacht = volgende - time.monotonic()
        if wacht > 0:
            time.sleep(min(wacht, 0.5))
        # Vaste cadans: reken vanaf de vorige deadline in plaats van
        # "antwoordtijd + interval". Anders zakt de verversing ongemerkt
        # weg zodra een antwoord van het bord even op zich laat wachten.
        volgende = max(volgende + interval, time.monotonic())

        if teller % 4 == 0:
            vers = client.gps()
            if vers is not None:
                # Onthou wanneer deze positie binnenkwam: een positie die
                # seconden oud is mag geen coördinaten meer opleveren.
                gps, gps_tijd = vers, time.monotonic()
        teller += 1

        if teller % 40 == 0:
            vorige_status = status_melding(client, vorige_status)

        start = time.monotonic()
        data = client.data()
        latentie = (time.monotonic() - start) * 1000.0

        if data is None:
            gemist += 1
            frames_fout += 1
            resultaten.append(0)
            if gemist <= 2:
                # Het bord herschrijft zijn JSON-buffer terwijl de http-taak
                # hem verstuurt: soms komt er een half antwoord. Meteen
                # opnieuw vragen kost 50 ms en houdt het beeld vloeiend.
                volgende = time.monotonic() + 0.05
            else:
                volgende = time.monotonic() + min(interval * gemist, 2.0)
            if gemist == 3 and "weg" not in gemeld:
                gemeld.add("weg")
                st.add_log("ESP32 antwoordt niet op %s" % base_url)
                if time.monotonic() - laatste_diagnose > 20:
                    laatste_diagnose = time.monotonic()
                    # Diagnose kost zelf seconden en pakt bewust het
                    # requestslot niet: op een eigen thread blijft het
                    # pollen doorgaan, zodat het beeld meteen terugkomt
                    # zodra de link er weer is.
                    threading.Thread(target=_diagnose_log, args=(base_url,),
                                     daemon=True).start()
            if gemist and gemist % 40 == 0:
                LOG.info("ESP32: %d polls op rij mislukt op %s", gemist,
                         base_url)
            continue

        body = esp32.parse_data(data, gps)
        if body is None:
            if not data.get("thermal_available", True):
                # Camera nog niet klaar: geen linkfout, wel even wachten.
                if "koud" not in gemeld:
                    gemeld.add("koud")
                    st.add_log("warmtecamera nog niet klaar")
                continue
            # Wél antwoord, maar geen bruikbaar frame (afgekapt of een
            # verkeerd aantal waarden). Als gemiste poll behandelen: één
            # keer opnieuw vragen levert meestal meteen een heel frame.
            gemist += 1
            frames_fout += 1
            resultaten.append(0)
            volgende = time.monotonic() + (
                0.05 if gemist <= 2 else min(interval * gemist, 2.0))
            if "leeg" not in gemeld:
                gemeld.add("leeg")
                st.add_log("thermisch frame ongeldig (geen %d waarden)"
                           % (app.cfg.width * app.cfg.height))
            continue

        if gemist >= 3:
            st.add_log("warmtebeeld hervat na %d gemiste polls" % gemist)
        gemeld.discard("weg")
        gemist = 0
        if gemeld:
            gemeld = set()
            st.add_log("thermische frames komen binnen")

        # Wat het bord zelf over dit frame zegt (min/max/hotspot, GPS):
        # klein genoeg om altijd in het vluchtbestand te zetten. Zo is
        # achteraf te zien of een melding van de sensor of van ons kwam.
        meta = {sleutel: data[sleutel]
                for sleutel in ("thermal_available", "thermal")
                if data.get(sleutel) is not None}
        if gps is not None:
            meta["gps"] = gps

        # Leeftijd van de positie, alleen als die uit de 1 Hz-/api/gps
        # komt: een `drone`-blok in /api/data is per frame vers.
        vers_drone = isinstance(data.get("drone"), dict) and bool(data["drone"])
        gps_leeftijd = None
        if not vers_drone and gps_tijd is not None:
            gps_leeftijd = round(time.monotonic() - gps_tijd, 1)
            body["drone"] = dict(body.get("drone") or {},
                                 age_s=gps_leeftijd)

        link = {"latency_ms": round(latentie, 1),
                "interval_s": round(interval, 3),
                "misses": frames_fout,
                "ok": frames_ok,
                "ok_pct": (round(100.0 * sum(resultaten) / len(resultaten), 1)
                           if resultaten else None),
                "gps_age_s": gps_leeftijd}

        try:
            app.ingest_body(body, link=link, meta=meta)
        except (ValueError, KeyError, TypeError, IndexError) as fout:
            frames_fout += 1
            app.note_ingest_rejected(str(fout))
            continue

        frames_ok += 1
        resultaten.append(1)
        if not camera_done:
            # Pas instellen als het bord echt antwoordt: zo kost een bord dat
            # uit staat geen extra wachttijd, en staan de instellingen goed
            # vóór de tweede frame binnenkomt.
            camera_done = True
            camera_opzetten(client, camera_size, camera_quality)
        latenties.append(latentie)
        del latenties[:-40]
        if latentie > interval * 1000:
            LOG.info("trage poll: %.0f ms (WiFi/MJPEG-stream deelt de band)",
                     latentie)

        if time.monotonic() - laatste_stat >= 30:
            laatste_stat = time.monotonic()
            recent = latenties or [0.0]
            LOG.info("link: %d frames ok, %d mislukt, %.0f%% van de laatste "
                     "%d polls goed, latentie gem %.0f ms (max %.0f ms)",
                     frames_ok, frames_fout,
                     (100.0 * sum(resultaten) / len(resultaten)
                      if resultaten else 0.0),
                     len(resultaten), sum(recent) / len(recent),
                     max(recent))


def main():
    parser = argparse.ArgumentParser(description="Sauron localhost-dashboard")
    parser.add_argument("--demo", action="store_true",
                        help="gesimuleerde live-feed i.p.v. wachten op hardware")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0",
                        help="bind-adres (standaard 0.0.0.0 zodat de ESP32 "
                             "de laptop over WiFi kan bereiken; gebruik "
                             "127.0.0.1 om alleen lokaal te luisteren)")
    parser.add_argument("--log-dir", default="logs",
                        help="map voor vluchtbestanden en logboeken")
    parser.add_argument("--launch-alt", type=float, default=None,
                        help="lanceerhoogte in meter MSL; nodig voor "
                             "brandcoördinaten als de firmware hem niet "
                             "meestuurt")
    parser.add_argument("--interval", type=float, default=0.25,
                        help="seconden tussen twee warmtebeeld-polls "
                             "(standaard 0.25 = 4 Hz; sensor is 8 Hz)")
    parser.add_argument("--esp-url", default=esp32.DEFAULT_BASE_URL,
                        help="basis-URL van de ESP32 (standaard %s)"
                             % esp32.DEFAULT_BASE_URL)
    parser.add_argument("--camera-size", default="480x320",
                        help="cameraresolutie voor de stock CameraWebServer "
                             "(standaard 480x320; 'none' slaat het over)")
    parser.add_argument("--camera-quality", type=int, default=10,
                        help="JPEG-kwaliteit 4 (best) .. 63 (kleinst), "
                             "standaard 10")
    parser.add_argument("--no-camera-setup", action="store_true",
                        help="camera-instellingen niet aanpassen")
    parser.add_argument("--capture", action="store_true",
                        help="bewaar ook elk ruw frame in het vluchtbestand, "
                             "zodat je drempels achteraf kunt hertunen "
                             "(python3 -m sauron.replay <bestand>)")
    parser.add_argument("--capture-rgb", type=float, default=0.0, metavar="SEC",
                        help="bewaar elke SEC seconden een RGB-foto in "
                             "<log-dir>/rgb (0 = uit)")
    args = parser.parse_args()

    logbestand = applog.setup(args.log_dir)
    applog.install_excepthooks()
    LOG.info("Sauron start; logbestand %s", logbestand)
    cfg = DEFAULT
    LOG.info("detectie: brand >= %.0f C en +%.0f C boven omgeving, "
             "verdacht >= %.0f C en +%.0f C, bevestigd na %d metingen",
             cfg.fire_min_abs_c, cfg.fire_min_delta_c,
             cfg.suspect_min_abs_c, cfg.suspect_min_delta_c,
             cfg.confirm_observations)

    recorder = FlightRecorder(args.log_dir, capture_frames=args.capture)
    app = App(recorder=recorder)
    if args.launch_alt is not None:
        app.set_launch_alt(args.launch_alt)
    app.start_watchdog()
    if args.demo:
        threading.Thread(target=demo_loop, args=(app,), daemon=True).start()
    else:
        threading.Thread(
            target=esp32_loop,
            args=(app, args.esp_url, args.interval,
                  parse_size(args.camera_size), args.camera_quality,
                  not args.no_camera_setup, args.capture_rgb),
            daemon=True).start()
    if args.capture:
        app.state.add_log("capture aan: ruwe frames worden opgenomen")
    if args.capture_rgb:
        app.state.add_log("RGB-foto's elke %.0f s naar %s/rgb"
                          % (args.capture_rgb, args.log_dir))
    run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
