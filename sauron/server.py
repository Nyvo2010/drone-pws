"""Localhost-server: live view op RGB, thermal, GPS, branden en logs.

Alleen stdlib (http.server + json + threading): geen Flask, geen
internet nodig. Alle REKENKRACHT staat op de laptop: de ESP32 en FC
leveren alleen ruwe data aan; pipeline.detect_event draait hier.

Routes:
- GET  /            dashboard (web/index.html, één bestand)
- GET  /api/state   JSON-snapshot (drone, branden, batterij-placeholder, logs)
- GET  /api/frame   thermisch frame voor het canvas (768 floats, 1 decimaal)
- POST /api/ingest  naad voor de teamgenoot: {"frame": [...768...],
                     "drone": {"lat","lon","alt_msl","heading_deg"},
                     "gps_alt_launch": ..} -> draait de pipeline, update State.

Gebruik (veld):  python3 dashboard.py            # wacht op POSTs
Gebruik (demo):  python3 dashboard.py --demo     # gesimuleerde live-feed
Open daarna: http://localhost:8000
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import autonomy, pipeline
from .config import DEFAULT
from .state import State

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
with open(WEB_DIR / "index.html", "rb") as _f:
    _INDEX = _f.read()  # één keer laden: dashboard verandert niet tijdens vlucht


class App:
    """Houder van State + de enige schrijver. Thread-safe via lock."""

    def __init__(self, cfg=DEFAULT):
        self.cfg = cfg
        self.state = State()
        self._lock = threading.Lock()

    def ingest(self, frame, drone, gps_alt_launch):
        """Verwerk één meetmoment en werk de staat bij. Retourneert resultaat.

        'drone' = {"lat","lon","alt_msl","heading_deg", optioneel
                    "fix","sats","hdop"} (FC/NMEA-kant, via ESP32-gateway).
        """
        resultaat = pipeline.detect_event(
            frame, drone["lat"], drone["lon"], drone["heading_deg"],
            drone["alt_msl"], gps_alt_launch, self.cfg,
        )
        with self._lock:
            st = self.state
            st.drone_lat = drone["lat"]
            st.drone_lon = drone["lon"]
            st.alt_msl = drone["alt_msl"]
            st.agl_m = resultaat["agl_m"]
            st.heading_deg = drone["heading_deg"]
            st.fc_fix = drone.get("fix")
            st.fc_sats = drone.get("sats")
            st.fc_hdop = drone.get("hdop")
            st.ambient = resultaat["ambient"]
            st.threshold = resultaat["threshold"]
            st.hotspots = resultaat["hotspots"]
            st.fires = resultaat["fires"]
            st.last_frame = list(frame)
            if resultaat["height_warning"]:
                st.add_log("LET OP hoogte: " + resultaat["height_warning"])
            for i, brand in enumerate(resultaat["fires"], 1):
                st.add_log(
                    "brand %d: %.1f C op %.6f, %.6f (%0.1f m)"
                    % (i, brand["max_temp"], brand["hotspot_lat"],
                       brand["hotspot_lon"], brand["afstand_m"])
                )
            # Autonomie-haak: nu uit -> alleen vastleggen dat hij uit staat.
            # Ooit: advies = autonomy.suggest_action(st) en doorgeven aan FC-team.
            if st.autonomy_enabled:
                st.autonomy_advice = autonomy.suggest_action(st)
        return resultaat

    def snapshot(self):
        """Thread-veilige kopie voor GET /api/state."""
        with self._lock:
            return self.state.public_dict()

    def frame_payload(self):
        """Thread-veilige kopie voor GET /api/frame (afgerond = kleiner)."""
        with self._lock:
            frame = self.state.last_frame
        if frame is None:
            return {"width": self.cfg.width, "height": self.cfg.height,
                    "cells": None}
        return {"width": self.cfg.width, "height": self.cfg.height,
                "cells": [round(v, 1) for v in frame]}


def make_handler(app):
    """Handler-fabriek: elke serverinstantie krijgt zijn eigen App."""

    class Handler(BaseHTTPRequestHandler):
        # Stil in het veld: geen logregel per request naar stdout.
        def log_message(self, *args):
            pass

        def _send(self, payload, content_type="application/json"):
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, obj):
            self._send(json.dumps(obj))

        def do_GET(self):
            if self.path == "/" or self.path.startswith("/?"):
                self._send(_INDEX, "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._send_json(app.snapshot())
            elif self.path == "/api/frame":
                self._send_json(app.frame_payload())
            else:
                self.send_error(404, "onbekend pad (alleen /, /api/state, /api/frame)")

        def do_POST(self):
            if self.path == "/api/ingest":
                try:
                    lengte = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(lengte).decode("utf-8"))
                    resultaat = app.ingest(body["frame"], body["drone"],
                                           body["gps_alt_launch"])
                except (ValueError, KeyError, TypeError) as fout:
                    self.send_error(400, "ongeldige ingest-body: %s" % fout)
                    return
                self._send_json({"ok": True, "n_fires": resultaat["n_fires"],
                                 "fires": resultaat["fires"]})
            elif self.path == "/api/log":
                try:
                    lengte = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(lengte).decode("utf-8"))
                    app.state.add_log(body["bericht"])
                except (ValueError, KeyError, TypeError) as fout:
                    self.send_error(400, "ongeldige log-body: %s" % fout)
                    return
                self._send_json({"ok": True})
            else:
                self.send_error(404, "POST-pad niet gevonden (alleen /api/ingest, /api/log)")

    return Handler


def run(app=None, host="127.0.0.1", port=8000):
    """Start de server (blokkeert). Alleen localhost: geen blootstelling."""
    app = app or App()
    server = ThreadingHTTPServer((host, port), make_handler(app))
    print("Sauron dashboard op http://%s:%d  (Ctrl+C om te stoppen)"
          % (host, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSauron gestopt.")
        server.shutdown()
