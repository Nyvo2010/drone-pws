"""Localhost-server: live view op RGB, thermal, GPS, branden en logs.

Alleen stdlib (http.server + json + threading): geen Flask, geen
internet nodig. Alle REKENKRACHT staat op de laptop: de ESP32 en FC
leveren alleen ruwe data aan; pipeline.detect_event draait hier.

Routes:
- GET  /                  dashboard (web/index.html, één bestand)
- GET  /api/state         JSON-snapshot (drone, branden, logs, vlucht)
- GET  /api/frame         thermisch frame voor het canvas (768 floats)
- POST /api/ingest        naad voor de ESP32/FC-forwarder
- POST /api/new-flight    sluit de huidige vlucht af en reset alle data
- GET  /api/flights       lijst met lokale vluchtbestanden (JSONL)
- GET  /api/flights/<f>   download één vluchtbestand

Gebruik (veld):  python3 dashboard.py            # wacht op POSTs
Gebruik (demo):  python3 dashboard.py --demo     # gesimuleerde live-feed
Open daarna: http://localhost:8000

De server luistert standaard op 0.0.0.0: alleen zo kan de ESP32 (die het
WiFi-access point host) de laptop op zijn LAN-IP bereiken. Wil je hem
lokaal houden, start dan met --host 127.0.0.1.
"""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import autonomy, pipeline, thermal
from .config import DEFAULT
from .state import State
from .tracking import FireTracker

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
with open(WEB_DIR / "index.html", "rb") as _f:
    _INDEX = _f.read()  # één keer laden: dashboard verandert niet tijdens vlucht

FIX_LABELS = {0: "geen", 1: "2D", 2: "3D", 3: "3D rtk"}


def _clock(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


def _fix_label(fix):
    if fix is None:
        return "onbekend"
    return FIX_LABELS.get(fix, str(fix))


def _first(obj, *namen):
    """Eerste niet-lege veld uit een dict (tolerant voor naamverschillen)."""
    for naam in namen:
        if obj.get(naam) is not None:
            return obj[naam]
    return None


def _flatten(frame):
    """Accepteer ook een genest 24x32-frame in plaats van 768 floats."""
    if frame and isinstance(frame[0], (list, tuple)):
        return [cel for rij in frame for cel in rij]
    return list(frame)


def _event_text(event):
    """Maak van een tracker-event één leesbare logregel."""
    brand = event["fire"]
    label = brand["id"]
    if event["type"] == "new":
        if brand.get("hotspot_lat") is None:
            return "nieuwe brand %s: %.1f C (locatie onbekend)" % (
                label, brand["max_temp"])
        return "nieuwe brand %s: %.1f C op %.6f, %.6f" % (
            label, brand["max_temp"],
            brand["hotspot_lat"], brand["hotspot_lon"])
    if event["type"] == "lost":
        return "brand %s uit beeld (laatst %.1f C om %s)" % (
            label, brand["max_temp"], _clock(brand["last_seen"]))
    if event["type"] == "reacquired":
        return "brand %s weer in beeld" % label
    if event["type"] == "archived":
        return "brand %s gearchiveerd" % label
    return "brand %s: %s" % (label, event["type"])


class App:
    """Houder van State + de enige schrijver. Thread-safe via lock."""

    def __init__(self, cfg=DEFAULT, recorder=None):
        self.cfg = cfg
        self.state = State()
        self._lock = threading.RLock()
        self.tracker = FireTracker(cfg)
        self.recorder = recorder
        self._stale = False
        self._closed = False
        # Lanceerhoogte onthouden: de ESP32 hoeft hem niet bij elk frame
        # opnieuw te sturen (scheelt een 400 als hij hem maar één keer
        # meestuurt). Per vlucht weer leeg.
        self._launch_alt = None
        self._warned = set()       # waarschuwingen die maar één keer loggen
        self._mislukt = 0          # aantal afgewezen POSTs
        self._laatste_melding = 0.0
        self.state.log_listener = self._on_log
        self._begin_flight()

    # -- vlucht -----------------------------------------------------------
    def _on_log(self, bericht, tijd):
        if self.recorder is not None:
            self.recorder.record({"type": "log", "message": bericht}, t=tijd)

    def _log_events(self, events, now):
        """Log + record tracker-events. Alleen aanroepen met de lock vast."""
        for event in events:
            self.state.add_log(_event_text(event))
            if self.recorder is not None:
                self.recorder.record({
                    "type": "fire_" + event["type"],
                    "fire": event["fire"],
                }, t=now)

    def _begin_flight(self):
        """Reset state + tracker en open (indien aanwezig) een nieuw bestand."""
        self.tracker.reset()
        self.state.reset()
        self._launch_alt = None
        self._warned = set()
        self._mislukt = 0
        self._laatste_melding = 0.0
        if self.recorder is not None:
            self.state.flight = self.recorder.start()
        self.state.add_log("vlucht gestart")

    def new_flight(self):
        """Sluit de huidige vlucht af, reset alles en start een nieuwe."""
        with self._lock:
            if self.recorder is not None:
                self.recorder.end("nieuwe vlucht")
            self._begin_flight()
            self._stale = False
            return self.state.flight

    def close(self):
        """Sta de watchdog en de recorder netjes stil (server stopt)."""
        self._closed = True
        with self._lock:
            if self.recorder is not None:
                self.recorder.end("server gestopt")

    def start_watchdog(self, interval=1.0, stale_after=5.0):
        """Log één keer als de datastroom stilvalt (en hervat wordt in ingest)."""
        def loop():
            while not self._closed:
                time.sleep(interval)
                now = time.time()
                with self._lock:
                    laatste = self.state.last_update
                    if laatste is not None and now - laatste > stale_after:
                        if not self._stale:
                            self._stale = True
                            self.state.add_log(
                                "geen data van de drone (%.0f s)" % (now - laatste)
                            )
                        # Ook zonder frames verloopt de brandtijd: markeer
                        # tracks als uit beeld en archiveer ze na de timeout,
                        # zodat de UI en het logboek niet liegen.
                        tracked, events = self.tracker.update([], now)
                        self.state.fires = tracked
                        self._log_events(events, now)
        threading.Thread(target=loop, daemon=True).start()

    # -- data -------------------------------------------------------------
    def _note_once(self, sleutel, bericht):
        """Log een waarschuwing één keer per vlucht (geen log-spam per frame)."""
        with self._lock:
            if sleutel in self._warned:
                return
            self._warned.add(sleutel)
            self.state.add_log(bericht)

    def note_ingest_rejected(self, reden):
        """Zet een afgewezen POST in het logboek.

        Zonder dit is een verkeerd JSON-contract van de ESP32 onzichtbaar:
        de terminal is stil en het dashboard zegt alleen "niet verbonden".
        De eerste drie meldingen komen altijd, daarna hooguit één per 10 s.
        """
        now = time.time()
        with self._lock:
            self._mislukt += 1
            if self._mislukt > 3 and now - self._laatste_melding < 10.0:
                return
            self._laatste_melding = now
            self.state.add_log(
                "ingest afgewezen (%d totaal): %s" % (self._mislukt, reden)
            )

    def ingest_body(self, body):
        """Lees één ESP32-pakket tolerant uit en verwerk het.

        De firmware is van een teamgenoot en gaat morgen voor het eerst
        live. Kleine naamverschillen (frame/temps, alt/alt_msl,
        heading/yaw) of een genest 24x32-frame mogen geen 400 kosten.
        Wat echt ontbreekt (het frame) blijft een duidelijke fout die in
        het logboek zichtbaar wordt.
        """
        if not isinstance(body, dict):
            raise ValueError("body moet een JSON-object zijn")

        frame = _first(body, "frame", "temps", "cells")
        if frame is None:
            raise ValueError("veld 'frame' ontbreekt (768 temperaturen)")
        frame = _flatten(frame)

        ruw = body.get("drone")
        if ruw is None:
            ruw = {}
        if not isinstance(ruw, dict):
            raise ValueError("veld 'drone' moet een object zijn")
        drone = {
            "lat": _first(ruw, "lat", "latitude"),
            "lon": _first(ruw, "lon", "lng", "longitude"),
            "alt_msl": _first(ruw, "alt_msl", "alt", "altitude"),
            "heading_deg": _first(ruw, "heading_deg", "heading", "yaw"),
            "fix": ruw.get("fix"),
            "sats": ruw.get("sats"),
            "hdop": ruw.get("hdop"),
        }

        launch = _first(body, "gps_alt_launch", "alt_launch", "launch_alt_msl")
        if launch is None:
            # Niet elke firmware stuurt dit bij elk frame mee. Onthoud de
            # waarde van eerder; is die er nog niet, dan melden we de brand
            # zonder coördinaten in plaats van de hele frame te weigeren.
            launch = self._launch_alt
            if launch is None:
                self._note_once(
                    "launch",
                    "geen lanceerhoogte ontvangen: branden zonder coördinaten",
                )
        else:
            self._launch_alt = launch

        if drone["heading_deg"] is None:
            self._note_once(
                "heading",
                "heading ontbreekt in het pakket: aanname 0 (coördinaten "
                "onbetrouwbaar)",
            )
        if drone["alt_msl"] is None:
            self._note_once("alt", "GPS-hoogte ontbreekt: geen AGL, geen locatie")

        return self.ingest(frame, drone, launch)

    def ingest(self, frame, drone, gps_alt_launch):
        """Verwerk één meetmoment en werk de staat bij. Retourneert resultaat.

        'drone' = {"lat","lon","alt_msl","heading_deg", optioneel
                    "fix","sats","hdop"} (FC/NMEA-kant, via ESP32-gateway).
        """
        now = time.time()
        # Dode pixels en I2C-uitschieters wegfilteren vóór detectie én vóór
        # het canvas: anders schaalt de kleurenkaart op 1200 C en lijkt de
        # rest van het veld ijs. sanitize_frame valideert ook (400 bij
        # NaN/tekst/verkeerde lengte).
        frame = thermal.sanitize_frame(frame, self.cfg)
        resultaat = pipeline.detect_event(
            frame, drone["lat"], drone["lon"], drone["heading_deg"],
            drone["alt_msl"], gps_alt_launch,
            gps_fix=drone.get("fix"), cfg=self.cfg,
        )

        with self._lock:
            tracked, events = self.tracker.update(resultaat["fires"], now)
            active = sum(1 for brand in tracked if brand["active"])

            st = self.state
            vorige_update = st.last_update
            if vorige_update is None:
                st.add_log("eerste frame van de ESP32 ontvangen")
            elif now - vorige_update > 3.5:
                st.add_log("data hervat na %.0f s" % (now - vorige_update))
            self._stale = False

            nieuwe_fix = drone.get("fix")
            if nieuwe_fix != st.fc_fix:
                st.add_log("GPS-fix: " + _fix_label(nieuwe_fix))

            # Hoogte en ontbrekende locatie zijn aparte meldingen; toon
            # ze allebei in plaats van de één door de ander te verbergen.
            waarschuwingen = [w for w in (resultaat["height_warning"],
                                          resultaat.get("location_warning")) if w]
            waarschuwing = " · ".join(waarschuwingen) or None
            if waarschuwing != st.warning:
                if waarschuwing:
                    st.add_log("LET OP: " + waarschuwing)
                else:
                    st.add_log("waarschuwing opgeheven")

            st.drone_lat = drone["lat"]
            st.drone_lon = drone["lon"]
            st.alt_msl = drone["alt_msl"]
            st.agl_m = resultaat["agl_m"]
            st.heading_deg = drone["heading_deg"]
            st.fc_fix = nieuwe_fix
            st.fc_sats = drone.get("sats")
            st.fc_hdop = drone.get("hdop")
            st.ambient = resultaat["ambient"]
            st.threshold = resultaat["threshold"]
            st.hotspots = resultaat["hotspots"]
            st.fires = tracked
            st.last_frame = list(frame)
            st.last_update = now
            st.warning = waarschuwing

            self._log_events(events, now)

            # Autonomie-haak: nu uit -> alleen vastleggen dat hij uit staat.
            if st.autonomy_enabled:
                st.autonomy_advice = autonomy.suggest_action(st)

            if self.recorder is not None:
                regel = {
                    "type": "ingest",
                    "gps_alt_launch": gps_alt_launch,
                    "drone": {
                        "lat": drone["lat"], "lon": drone["lon"],
                        "alt_msl": drone["alt_msl"],
                        "heading_deg": drone["heading_deg"],
                        "fix": nieuwe_fix,
                        "sats": drone.get("sats"),
                        "hdop": drone.get("hdop"),
                    },
                    "thermal": {
                        "ambient": resultaat["ambient"],
                        "threshold": resultaat["threshold"],
                        "n_hotspots": len(resultaat["hotspots"]),
                        "n_fires": active,
                    },
                    "agl_m": resultaat["agl_m"],
                    "height_warning": resultaat["height_warning"],
                    "location_warning": resultaat.get("location_warning"),
                    "warning": waarschuwing,
                    "hotspots": resultaat["hotspots"],
                    "fires": tracked,
                }
                if getattr(self.recorder, "capture_frames", False):
                    # Ruw frame bewaren: hiermee kun je na de vlucht
                    # drempels hertunen zonder opnieuw te vliegen.
                    regel["cells"] = [round(v, 1) for v in frame]
                self.recorder.record(regel, t=now)

        return {**resultaat, "fires": tracked, "n_fires": active}

    def snapshot(self):
        """Thread-veilige kopie voor GET /api/state.

        De brandstatus wordt bij elk verzoek opnieuw uit de tracker
        afgeleid: zo wordt een brand ook 'uit beeld' als de datastroom
        helemaal stopt (de watchdog hoeft dan niet elk frame te wachten).
        """
        with self._lock:
            self.state.fires = self.tracker.snapshot(time.time())
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

    def list_flights(self):
        if self.recorder is None:
            return []
        return self.recorder.list_flights()

    def read_flight(self, name):
        if self.recorder is None:
            return None
        path = self.recorder.path_for(name)
        return path.read_bytes() if path is not None else None


def make_handler(app):
    """Handler-fabriek: elke serverinstantie krijgt zijn eigen App."""

    class Handler(BaseHTTPRequestHandler):
        # Stil in het veld: geen logregel per request naar stdout.
        def log_message(self, *args):
            pass

        def _send(self, payload, content_type="application/json", headers=None):
            if isinstance(payload, str):
                payload = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            for sleutel, waarde in (headers or {}).items():
                self.send_header(sleutel, waarde)
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
            elif self.path == "/api/flights":
                self._send_json({"flights": app.list_flights()})
            elif self.path.startswith("/api/flights/"):
                naam = unquote(self.path[len("/api/flights/"):])
                data = app.read_flight(naam)
                if data is None:
                    self.send_error(404, "vluchtbestand niet gevonden")
                    return
                self._send(data, "application/x-ndjson", {
                    "Content-Disposition": 'attachment; filename="%s"' % naam,
                })
            else:
                self.send_error(404, "onbekend pad")

        def do_POST(self):
            if self.path == "/api/ingest":
                try:
                    lengte = int(self.headers.get("Content-Length", 0))
                    if lengte <= 0:
                        raise ValueError("lege body")
                    body = json.loads(self.rfile.read(lengte).decode("utf-8"))
                    resultaat = app.ingest_body(body)
                except (ValueError, KeyError, TypeError, IndexError) as fout:
                    # Ook in het dashboard zetten: anders is een verkeerd
                    # contract van de ESP32 onzichtbaar in het veld.
                    app.note_ingest_rejected(str(fout))
                    self.send_error(400, "ongeldige ingest-body: %s" % fout)
                    return
                self._send_json({"ok": True, "n_fires": resultaat["n_fires"],
                                 "fires": resultaat["fires"]})
            elif self.path == "/api/new-flight":
                try:
                    vlucht = app.new_flight()
                except OSError as fout:
                    self.send_error(500, "nieuwe vlucht mislukt: %s" % fout)
                    return
                self._send_json({"ok": True, "flight": vlucht})
            else:
                self.send_error(404, "POST-pad niet gevonden")

    return Handler


def lan_ip():
    """Best-effort LAN-IP van deze laptop (voor de URL die de ESP32 post).

    Een UDP-connect verzendt niets; hij laat de kernel alleen de route
    kiezen. Zonder netwerk (offline demo) geven we None terug.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.168.4.1", 81))
            return sock.getsockname()[0]
    except OSError:
        return None


def run(app=None, host="0.0.0.0", port=8000):
    """Start de server (blokkeert).

    host="0.0.0.0" is bewust: de ESP32 moet de laptop over WiFi kunnen
    bereiken. Gebruik "127.0.0.1" om de server lokaal te houden.
    """
    app = app or App()
    server = ThreadingHTTPServer((host, port), make_handler(app))
    print("Sauron dashboard op http://localhost:%d  (Ctrl+C om te stoppen)"
          % port)
    ip = lan_ip() if host in ("0.0.0.0", "::") else None
    if ip:
        print("Vanaf ESP32/andere apparaten: http://%s:%d" % (ip, port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSauron gestopt.")
    finally:
        server.server_close()
        app.close()
