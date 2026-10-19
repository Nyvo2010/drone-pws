"""Startpunt dashboard: server + (optioneel) gesimuleerde live-feed.

Veld (echt):   python3 dashboard.py
  -> server wacht op POST /api/ingest van de ESP32/FC-forwarder
     (teamgenoot). Alle processing draait hier op de laptop.

Demo (geen hardware):  python3 dashboard.py --demo
  -> achtergrondthread post elke seconde een nep-frame (vlek drijft
     langzaam) + vaste dronepositie. Handig voor UI-check zonder drone.

Open daarna: http://localhost:8000

Elke vlucht wordt gelogd als JSONL in `logs/` (aanpasbaar met --log-dir);
de header heeft een nieuwe-vlucht-knop die de live-data reset en een nieuw
bestand opent.
"""

import argparse
import math
import threading
import time

from sauron.flightlog import FlightRecorder
from sauron.server import App, run
from sauron.sim import make_frame

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
        frame = make_frame(vlekken=[(x, 10, 85.0, 2.5)], seed=t)
        app.ingest(frame, DRONE, ALT_LANCERING)
        t += 1
        time.sleep(interval)


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
                        help="map voor vluchtbestanden (JSONL per vlucht)")
    parser.add_argument("--capture", action="store_true",
                        help="bewaar ook elk ruw frame in het vluchtbestand, "
                             "zodat je drempels achteraf kunt hertunen "
                             "(python3 -m sauron.replay <bestand>)")
    args = parser.parse_args()

    recorder = FlightRecorder(args.log_dir, capture_frames=args.capture)
    app = App(recorder=recorder)
    app.start_watchdog()
    if args.demo:
        draad = threading.Thread(target=demo_loop, args=(app,), daemon=True)
        draad.start()
    else:
        app.state.add_log("wachten op POST /api/ingest (ESP32/FC-forwarder)")
    if args.capture:
        app.state.add_log("capture aan: ruwe frames worden opgenomen")
    run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
