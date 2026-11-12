"""Zelftest: doet de laptop-kant het? (thermisch + camera)

Twee vragen beantwoorden zonder vliegtuig:

1. Werkt de thermische keten op de laptop? -> we posten een synthetisch
   warm frame met GPS naar /api/ingest en kijken of er een brand met
   coördinaten uit komt en of het vluchtbestand gevuld wordt.
2. Werkt de GPS-route zoals de drone hem straks loopt? -> we posten een
   frame met RUWE NMEA (GGA/RMC) in plaats van geparseerde velden: de
   ESP32 hoeft alleen de serial-regels van G37 door te geven.
3. Werkt de ESP32? -> /api/status, /api/data en /capture. Het frame dat
   het bord echt teruggeeft gaat door dezelfde detectie als in het veld.
   Dit stuk slaat over als de drone niet bereikbaar is (dan is dat geen
   fout, maar wel iets om te weten).

Gebruik:
  python3 selftest.py                      # alleen de laptop-kant
  python3 selftest.py --esp32-url http://192.168.4.1   # incl. drone

Exit 0 = alles ok, exit 1 = er is iets stuk.
"""

import argparse
import json
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, ".")  # run vanaf repo-root

from sauron import esp32
from sauron.flightlog import FlightRecorder
from sauron.server import App, make_handler
from sauron.sim import make_frame

DRONE = {"lat": 52.090000, "lon": 4.310000, "alt_msl": 25.0,
         "heading_deg": 90.0, "fix": 3, "sats": 12, "hdop": 0.9}
ALT_LANCERING = 10.0

# Wat een GEP-M10 op zijn serial-poort zet (G37 op de ESP32). De laptop
# leest deze zinnen, zodat de firmware niets hoeft te parsen.
NMEA = ("$GPGGA,123519,5205.4000,N,00418.6000,E,1,08,0.9,25.0,M,0.0,M,,*47\r\n"
        "$GPRMC,123519,A,5205.4000,N,00418.6000,E,022.4,084.4,230394,"
        "003.1,W*6A")

mislukt = 0


def check(ok, tekst, detail=""):
    """Print één check-uiteinde; houd de teller bij."""
    global mislukt
    if not ok:
        mislukt += 1
    print("[%s] %s%s" % ("ok" if ok else "FOUT", tekst,
                         ("  -> " + detail) if detail else ""))


def _vraag(url, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_thermische_keten():
    """Start de server op een vrije poort en stuur één warm frame."""
    print("\n== thermische keten (laptop) ==")
    with tempfile.TemporaryDirectory() as logmap:
        recorder = FlightRecorder(logmap)
        app = App(recorder=recorder)
        app.start_flight("zelftest")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        poort = httpd.server_address[1]
        draad = threading.Thread(target=httpd.serve_forever, daemon=True)
        draad.start()
        base = "http://127.0.0.1:%d" % poort
        try:
            state = _vraag(base + "/api/state")
            check("thermal" in state, "/api/state antwoordt",
                  "sleutels: %s" % ", ".join(sorted(state)[:6]))

            frame = make_frame(vlekken=[(16, 10, 250.0, 2.5)])
            payload = {"frame": frame, "drone": DRONE,
                       "gps_alt_launch": ALT_LANCERING}
            antwoord = _vraag(base + "/api/ingest", payload)
            check(antwoord.get("ok") is True, "POST /api/ingest geaccepteerd",
                  json.dumps(antwoord)[:120])
            check(antwoord.get("n_fires") == 0
                  and antwoord.get("n_suspects") == 1,
                  "eerste frame is 'verdacht', nog geen brand",
                  "n_fires=%s n_suspects=%s" % (antwoord.get("n_fires"),
                                                antwoord.get("n_suspects")))
            # Tweede frame: dezelfde plek heet, maar een nieuwe meting. (Een
            # identiek frame telt bewust niet als tweede meting.)
            tweede = dict(payload, frame=list(frame))
            tweede["frame"][0] += 0.1
            antwoord = _vraag(base + "/api/ingest", tweede)
            check(antwoord.get("n_fires", 0) >= 1,
                  "warme vlek bevestigd als brand in twee frames",
                  "n_fires=%s" % antwoord.get("n_fires"))

            state = _vraag(base + "/api/state")
            check(state.get("last_update") is not None,
                  "tijdstip van de ingest vastgelegd")
            check(state.get("thermal", {}).get("ambient") is not None,
                  "omgevingstemperatuur bepaald",
                  "ambient=%s" % state.get("thermal", {}).get("ambient"))
            branden = state.get("fires") or []
            check(len(branden) >= 1, "brand staat in de staat")
            if branden:
                brand = branden[0]
                check(brand.get("hotspot_lat") is not None
                      and brand.get("hotspot_lon") is not None,
                      "brand heeft GPS-coördinaten",
                      "%s, %s" % (brand.get("hotspot_lat"), brand.get("hotspot_lon")))
                check(brand.get("max_temp", 0) > 60.0,
                      "brandtemperatuur is geloofwaardig",
                      "%.1f C" % brand.get("max_temp", 0))

            bestanden = list(Path(logmap).glob("*.jsonl"))
            check(len(bestanden) == 1, "vluchtbestand aangemaakt",
                  ", ".join(b.name for b in bestanden))
            if bestanden:
                regels = [json.loads(l) for l in
                          bestanden[0].read_text().splitlines() if l.strip()]
                types = [r.get("type") for r in regels]
                check("ingest" in types, "ingest weggeschreven",
                      "types: %s" % sorted(set(types)))
                check("fire_new" in types, "brand weggeschreven",
                      "types: %s" % sorted(set(types)))
                naam = next((r.get("flight", {}).get("name") for r in regels
                             if r.get("type") == "flight_start"), None)
                check(naam == "zelftest", "vluchtnaam in het bestand",
                      str(naam))
        finally:
            httpd.shutdown()
            httpd.server_close()
            app.close()


def test_nmea_keten():
    """Frame + ruwe NMEA, precies zoals de ESP32 hem straks post."""
    print("\n== gps via de esp32 (ruwe NMEA) ==")
    with tempfile.TemporaryDirectory() as logmap:
        app = App(recorder=FlightRecorder(logmap))
        # De firmware stuurt voorlopig geen lanceerhoogte mee.
        app._launch_alt = ALT_LANCERING
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
        draad = threading.Thread(target=httpd.serve_forever, daemon=True)
        draad.start()
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        try:
            antwoord = _vraag(base + "/api/ingest", {
                "frame": make_frame(vlekken=[(16, 10, 250.0, 2.5)]),
                "nmea": NMEA,
            })
            check(antwoord.get("ok") is True,
                  "POST met ruwe NMEA geaccepteerd",
                  json.dumps(antwoord)[:120])
            staat = _vraag(base + "/api/state")
            drone = staat.get("drone") or {}
            check(drone.get("lat") is not None
                  and abs(drone["lat"] - 52.09) < 1e-3,
                  "positie uit NMEA in de staat", str(drone.get("lat")))
            check(drone.get("fc_fix") == 2,
                  "fix uit GGA (kwaliteit 1 = 3D)", str(drone.get("fc_fix")))
            check(drone.get("fc_sats") == 8, "satellieten uit GGA",
                  str(drone.get("fc_sats")))
            check(drone.get("agl_m") is not None
                  and abs(drone["agl_m"] - 15.0) < 0.2,
                  "AGL = GPS-hoogte - lanceerhoogte",
                  str(drone.get("agl_m")))
            branden = staat.get("fires") or []
            check(bool(branden) and branden[0].get("hotspot_lat") is not None,
                  "brand met coördinaten uit de NMEA-positie")
        finally:
            httpd.shutdown()
            httpd.server_close()
            app.close()


def test_esp32_data(base_url):
    """De eigen firmware: /api/status, /api/data en /capture.

    Dit is de route die het bord nu serveert. Het frame dat de ESP32
    écht teruggeeft gaat door dezelfde detectie als in het veld, zodat
    je ziet of de keten met DEZE data een brand oplevert.
    """
    print("\n== esp32-data (/api/status, /api/data, /capture) ==")
    client = esp32.Esp32(base_url, timeout=6.0)

    status = client.api_status()
    check(status is not None, "/api/status leesbaar")
    if status:
        print("       wifi: %s | camera: %s | thermal: %s | gps: %s"
              % (json.dumps(status.get("wifi")), status.get("camera"),
                 status.get("thermal"), json.dumps(status.get("gps"))))
        gps = status.get("gps") or {}
        if gps.get("location_valid"):
            check(True, "GPS heeft een geldige locatie")
        else:
            print("       [--] GPS: zinnen ontvangen=%s, locatie geldig=%s "
                  "(buiten of nog geen fix)"
                  % (gps.get("data_seen"), gps.get("location_valid")))

    data = client.data()
    check(data is not None, "/api/data leesbaar")
    if data is None:
        return
    beschikbaar = bool(data.get("thermal_available", True))
    frame = data.get("frame")
    if not beschikbaar or not frame:
        print("       [--] warmtecamera nog niet klaar "
              "(thermal_available=%s) — nog geen frame om te testen"
              % data.get("thermal_available"))
        return
    check(True, "warmtebeeld ontvangen",
          "%d waarden" % len(frame) if not isinstance(frame[0], list)
          else "%dx%d" % (len(frame), len(frame[0])))

    # Het echte frame door de echte detectie: dat is de bewijsvraag.
    gps_data = client.gps()
    body = esp32.parse_data(data, gps_data)
    check(body is not None, "frame om te zetten naar een ingest-pakket")
    if body is None:
        return
    app = App()
    try:
        resultaat = app.ingest_body(body)
        check(True, "ingest van het echte ESP32-frame geaccepteerd",
              "omgeving %.1f C, drempel %.1f C, %d hotspot(s)"
              % (resultaat["ambient"], resultaat["threshold"],
                 resultaat["n_hotspots"]))
        if resultaat["n_fires"]:
            brand = resultaat["fires"][0]
            print("       brand: %.1f C op (%s, %s)"
                  % (brand.get("max_temp"), brand.get("x"), brand.get("y")))
        else:
            print("       [--] geen brand in dit beeld (koud tafereel is "
                  "ook een geldige uitkomst)")
    except (ValueError, KeyError, TypeError, IndexError) as fout:
        check(False, "ingest van het echte ESP32-frame", str(fout))
    finally:
        app.close()

    # Deze firmware heeft géén /capture (alleen /api/* en :81/stream): een
    # stilstaand beeld bestaat hier niet. Dat is een eigenschap van de build,
    # geen storing, dus melden als overgeslagen in plaats van als fout --
    # anders faalt de zelftest altijd op iets wat niet te repareren is.
    jpeg = client.capture()
    if jpeg:
        maat = esp32.jpeg_size(jpeg)
        check(True, "/capture levert een JPEG",
              "%s, %d bytes"
              % (("%dx%d" % maat) if maat else "onbekend formaat", len(jpeg)))
    else:
        print("       [--] /capture niet ondersteund door deze firmware "
              "(geen stilstaand beeld; RGB loopt via de stream op :81)")


def _stream_meten(url, seconden=3.0):
    """Lees de MJPEG-stream `seconden` lang: (fps, bytes/s, hoogste gat ms).

    Geeft (None, None, reden) als de stream niet te openen is. Bewust kort
    en met een eigen socket: de firmware heeft één stream-slot, dus dit is
    dezelfde weg als de browser neemt.
    """
    delen = urllib.parse.urlsplit(url)
    host = delen.hostname or "192.168.4.1"
    poort = delen.port or 81
    try:
        sock = socket.create_connection((host, poort), 2.0)
    except OSError as fout:
        return None, None, str(fout)
    sock.settimeout(2.0)
    frames = []
    totaal = 0
    try:
        sock.sendall(("GET /stream HTTP/1.1\r\nHost: %s\r\n"
                      "Connection: close\r\n\r\n" % host).encode())
        buf = b""
        start = time.monotonic()
        while time.monotonic() - start < seconden:
            try:
                blok = sock.recv(65536)
            except socket.timeout:
                break
            if not blok:
                break
            buf += blok
            while True:
                kop = buf.find(b"Content-Length: ")
                if kop < 0:
                    break
                eind = buf.find(b"\r\n", kop)
                try:
                    lengte = int(buf[kop + 16:eind])
                except ValueError:
                    break
                begin = buf.find(b"\r\n\r\n", eind)
                if begin < 0 or len(buf) < begin + 4 + lengte:
                    break
                buf = buf[begin + 4 + lengte:]
                frames.append(time.monotonic())
                totaal += lengte
    finally:
        sock.close()
    if len(frames) < 2:
        return None, None, "geen frames"
    duur = frames[-1] - frames[0]
    gaten = [(frames[i + 1] - frames[i]) * 1000.0
             for i in range(len(frames) - 1)]
    return (len(frames) - 1) / duur, totaal / duur, max(gaten)


def test_link(base_url):
    """Meet ALLE signalen apart: latentie, warmtebeeld, GPS-UART, RGB, WiFi.

    De camera werkt in de praktijk vaak wel terwijl de GPS stil is of de
    warmtecamera leesfouten geeft. Deze check noemt elk signaal apart, met
    cijfers, zodat een storing niet als "geen data" eindigt.
    """
    print("\n== link: alle signalen ==")
    client = esp32.Esp32(base_url, timeout=2.0, read_timeout=4.0)
    if not client.bereikbaar():
        print("[--] overgeslagen: ESP32 niet bereikbaar op %s" % base_url)
        return

    # 1. Latentie van /api/data, in hetzelfde tempo als het dashboard.
    latenties = []
    gelukt = 0
    laatste = None
    for _ in range(12):
        begin = time.monotonic()
        data = client.data()
        latenties.append((time.monotonic() - begin) * 1000.0)
        if data is not None:
            gelukt += 1
            laatste = data
        time.sleep(0.2)
    latenties.sort()
    check(gelukt == len(latenties), "12 polls op /api/data",
          "%d/12 ok, mediaan %.0f ms, p95 %.0f ms, max %.0f ms"
          % (gelukt, latenties[len(latenties) // 2],
             latenties[int(len(latenties) * 0.95) - 1], latenties[-1]))
    if laatste is None:
        return

    # 2. Warmtebeeld: aanwezig, 768 waarden, plausibel bereik.
    frame = laatste.get("frame")
    if frame is None:
        melding = str((laatste.get("thermal") or {}).get("status") or "")
        check(False, "warmtebeeld in /api/data",
              "frame=null (thermal_available=%s%s)"
              % (laatste.get("thermal_available"),
                 ", " + melding if melding else ""))
    else:
        if isinstance(frame[0], (list, tuple)):
            waarden = [v for rij in frame for v in rij if v is not None]
        else:
            waarden = [v for v in frame if v is not None]
        check(len(waarden) == 768, "warmtebeeld heeft 768 waarden",
              "%d waarden" % len(waarden))
        if waarden:
            print("       bereik %.1f .. %.1f C, mediaan %.1f C, %d dode pixels"
                  % (min(waarden), max(waarden),
                     sorted(waarden)[len(waarden) // 2], 768 - len(waarden)))

    # 3. GPS-UART: een stille UART is een kabel/stroomfout, geen "geen fix".
    voor = (client.api_status() or {}).get("gps") or {}
    time.sleep(3)
    status = client.api_status() or {}
    gps = status.get("gps") or {}
    bytes_delta = int(gps.get("bytes_seen") or 0) - \
        int(voor.get("bytes_seen") or 0)
    check(bytes_delta > 0, "GPS-UART levert bytes",
          "%d bytes in 3 s, UBX-berichten %s, checksumfouten %s"
          % (bytes_delta, gps.get("ubx_messages"),
             gps.get("checksum_failures")))
    print("       fix %s, %s satellieten, HDOP %s, baud %s"
          % (gps.get("fix_type"), gps.get("satellites"),
             (client.gps() or {}).get("hdop"), gps.get("baud")))
    uptime = (status.get("stream") or {}).get("last_frame_at_ms")
    if isinstance(uptime, int) and uptime < 60000:
        print("       [--] bord pas %d s op: na een herstart beginnen de "
              "GPS-bytes weer bij 0" % (uptime // 1000))
    if bytes_delta > 0 and not gps.get("location_valid"):
        print("       [--] nog geen fix: binnen of geen vrij zicht op de lucht")

    # 4. RGB-stream: fps en bytes/s zoals de browser hem ziet.
    fps, bytes_sek, gat = _stream_meten(esp32.stream_url(base_url))
    if fps is None:
        # De firmware serveert één stream-client (de handlerlus stopt pas bij
        # een send-fout). Telt het bord wél frames, dan houdt een andere tab
        # of app het slot bezet -- dat is de waarschijnlijke oorzaak, niet
        # een netwerkstoring. Zeg dat erbij.
        stream = status.get("stream") or {}
        frames = stream.get("frames_sent") or 0
        extra = ""
        if frames:
            extra = ("; frames_sent=%s: het enige stream-slot is bezet door "
                     "een andere client (tab op 192.168.4.1 of :81) -- sluit "
                     "die en herhaal de test" % frames)
        check(False, "MJPEG-stream op :81 leesbaar", "%s%s" % (gat, extra))
    else:
        check(True, "MJPEG-stream",
              "%.1f fps, %.0f kB/s, hoogste gat %.0f ms"
              % (fps, (bytes_sek or 0) / 1024.0, gat))

    # 5. WiFi: de AP meldt de RSSI van deze laptop.
    wifi = status.get("wifi") or {}
    check(True, "WiFi-signaal", "%s (%s dBm, %s%%), %s client(s)"
          % (wifi.get("quality"), wifi.get("rssi_dbm"),
             wifi.get("signal_percent"), wifi.get("clients")))


def test_esp32(base_url):
    """Lees de camera-instellingen van de ESP32 uit (best effort)."""
    print("\n== esp32 ==")
    client = esp32.Esp32(base_url, timeout=4.0)
    if not client.bereikbaar():
        # Niet bereikbaar is geen fout: de zelftest draait ook zonder drone.
        print("[--] overgeslagen: ESP32 niet bereikbaar op %s" % base_url)
        print("       (evt. staat de laptop niet op het drone-net "
              "192.168.4.0/24?)")
        return
    check(True, "ESP32 bereikbaar op %s" % base_url)

    if client.api_status() is not None:
        # Eigen firmware: geen CameraWebServer-paden. De camera-instellingen
        # zijn hier niet op afstand te zetten; data + beeld zijn dat wel.
        test_esp32_data(base_url)
        print("       [--] camera-instellingen overgeslagen: deze firmware "
              "heeft geen /status of /control")
        return

    status = client.status()
    check(status is not None, "/status leesbaar")
    if status is None:
        return
    rapport = esp32.camera_report(status)
    print("       camera: %s | kwaliteit %s | spiegel %s | sensor %s"
          % (rapport.get("resolutie") or rapport.get("framesize_label"),
             rapport.get("quality"), rapport.get("hmirror"),
             rapport.get("sensor")))
    print("       %d sensor-registers gelezen" % len(rapport.get("registers", {})))

    jpeg = client.capture()
    check(jpeg is not None, "/capture levert een JPEG")
    if jpeg:
        maat = esp32.jpeg_size(jpeg)
        check(maat is not None, "JPEG-resolutie te meten",
              "bytes=%d" % len(jpeg))
        if maat:
            print("       gemeten resolutie: %dx%d" % maat)
            framesize = status.get("framesize")
            label = esp32.framesize_label(framesize)
            if label:
                check("%dx%d" % maat == label.split(" ", 1)[-1],
                      "resolutie klopt met de ingestelling (%s)" % label,
                      "gemeten %dx%d" % maat)

    gewenst = esp32.framesize_for(480, 320)
    if status.get("framesize") != gewenst:
        print("       LET OP: framesize is %s, gewenst 480x320 (waarde %s)"
              % (status.get("framesize"), gewenst))
        print("       pas dit toe met:  python3 dashboard.py "
              "--camera-size 480x320 --camera-quality 10")
    if status.get("hmirror") != 1:
        print("       LET OP: horizontale spiegeling staat UIT "
              "(dashboard.py zet hem standaard aan)")
    if status.get("quality", 99) > 20:
        print("       LET OP: JPEG-kwaliteit %s is laag (4 = beste)"
              % status.get("quality"))


def main():
    parser = argparse.ArgumentParser(description="Sauron zelftest")
    parser.add_argument("--esp32-url", default=esp32.DEFAULT_BASE_URL,
                        help="controlsserver van de ESP32 (optioneel)")
    args = parser.parse_args()

    print("Sauron zelftest")
    test_thermische_keten()
    test_nmea_keten()
    test_esp32(args.esp32_url)
    test_link(args.esp32_url)

    print("\n%s" % ("ALLE CHECKS OK" if mislukt == 0
                    else "%d CHECK(S) MISLUKT" % mislukt))
    return 0 if mislukt == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
