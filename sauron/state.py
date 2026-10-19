"""Gedeelde staat: het enige aanspreekpunt tussen modules.

Architectuur (bewust zo plat mogelijk, klaar voor latere autonomie):

    sensoren (ESP32/FC) --POST--> server.ingest --+--> pipeline (perceptie)
                                                  |
                                                  v
                                          State (DIT BESTAND)
                                          ^                |
                          dashboard leest |                | autonomie leest LATER
                                          |                v
                                   web/index.html    autonomy.suggest_action (stub)

Regels:
- Alleen server.py schrijft (onder lock); dashboard en autonomie lezen.
- pipeline.py blijft puur (geen I/O) en kent deze State niet.
- Velden als batterij zijn nu placeholders (None): de UI toont "—".
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class State:
    """Alles wat het dashboard toont en latere autonomie nodig heeft."""

    # -- Drone-positie (van flight controller via NMEA, door ESP32 geforwarded) --
    drone_lat: float | None = None
    drone_lon: float | None = None
    alt_msl: float | None = None   # GPS-hoogte t.o.v. zeeniveau
    agl_m: float | None = None     # hoogte boven lanceerpunt (zie geo.py)
    heading_deg: float = 0.0
    fc_fix: int | None = None      # GPS-fixkwaliteit (0=geen, 1=2D, 2=3D, 3=GTX)
    fc_sats: int | None = None     # aantal satellieten
    fc_hdop: float | None = None   # horizontale preciseheidsindicatie

    # -- Perceptie (van pipeline.detect_event) -------------------------
    ambient: float | None = None
    threshold: float | None = None
    hotspots: list = field(default_factory=list)  # alle blobs (diagnose)
    fires: list = field(default_factory=list)     # alleen branden + locatie
    last_frame: list | None = None  # laatste 768 floats (voor /api/frame)
    # Wandkloktijd (epoch) van de laatste ingest; de UI toont hiermee of de
    # feed nog leeft in plaats van oude waarden als "live" te presenteren.
    last_update: float | None = None
    # Actieve waarschuwing van de laatste meting (hoogte of ontbrekende
    # locatie), zodat de operator hem ziet en niet alleen in het logboek.
    warning: str | None = None

    # -- Vlucht -----------------------------------------------------------
    # {id, file, started} van de recorder; None als er niet gelogd wordt.
    flight: dict | None = None

    # -- Placeholders (teamgenoot / later) ------------------------------
    # Batterij: straks {"voltage_v": .., "percent": ..}; nu None = "—".
    battery: dict | None = None
    mode: str = "MANUAL"  # MANUAL nu; AUTO pas bij autonomie-fase
    rgb_url: str = "http://192.168.4.1:81/stream"  # ESP32 MJPEG (FC-team: aanpasbaar)

    # -- Autonomie-haak --------------------------------------------------
    # False = mens vliegt, suggest_action() wordt genegeerd. Ooit True +
    # echte regelaar erachter; de server stuurt dan niets aan, hij legt
    # alleen het advies naast de staat (FC-team leest het uit).
    autonomy_enabled: bool = False
    autonomy_advice: dict | None = None

    # -- Logboek (ringbuffer) --------------------------------------------
    _logs: list = field(default_factory=list, repr=False)
    _log_times: list = field(default_factory=list, repr=False)
    # Wordt door server.App gezet om elke logregel ook naar het
    # vluchtbestand te schrijven. State blijft zelf I/O-vrij.
    log_listener: Callable | None = field(default=None, repr=False, compare=False)
    MAX_LOGS: int = 50

    def add_log(self, bericht):
        """Voeg een regel toe met tijdstip; oudste valt weg bij > MAX_LOGS."""
        tijd = time.time()
        self._logs.append(bericht)
        self._log_times.append(tijd)
        overschot = len(self._logs) - self.MAX_LOGS
        if overschot > 0:
            # Beide lijsten even lang houden: de UI koppelt ze op index.
            del self._logs[:overschot]
            del self._log_times[:overschot]
        if self.log_listener is not None:
            self.log_listener(bericht, tijd)

    def reset(self):
        """Nieuwe vlucht: vluchtdata leeg, listener en instellingen behouden."""
        self.drone_lat = None
        self.drone_lon = None
        self.alt_msl = None
        self.agl_m = None
        self.heading_deg = 0.0
        self.fc_fix = None
        self.fc_sats = None
        self.fc_hdop = None
        self.ambient = None
        self.threshold = None
        self.hotspots = []
        self.fires = []
        self.last_frame = None
        self.last_update = None
        self.warning = None
        self.flight = None
        self.battery = None
        self.mode = "MANUAL"
        self.rgb_url = "http://192.168.4.1:81/stream"
        self.autonomy_advice = None
        self._logs.clear()
        self._log_times.clear()

    def public_dict(self):
        """JSON-veilige snapshot voor GET /api/state (geen raw frame)."""
        return {
            "drone": {
                "lat": self.drone_lat,
                "lon": self.drone_lon,
                "alt_msl": self.alt_msl,
                "agl_m": self.agl_m,
                "heading_deg": self.heading_deg,
                "fc_fix": self.fc_fix,
                "fc_sats": self.fc_sats,
                "fc_hdop": self.fc_hdop,
            },
            "thermal": {
                "ambient": self.ambient,
                "threshold": self.threshold,
                "n_hotspots": len(self.hotspots),
                # Alleen branden die nog binnen de grace-periode gezien zijn;
                # uit-beeld-tracks blijven in de lijst voor herdetectie.
                "n_fires": sum(1 for f in self.fires if f.get("active", True)),
            },
            "fires": self.fires,
            "battery": self.battery,  # None -> UI toont placeholder
            "mode": self.mode,
            "rgb_url": self.rgb_url,
            "last_update": self.last_update,
            "warning": self.warning,
            "flight": self.flight,
            "autonomy": {
                "enabled": self.autonomy_enabled,
                "advice": self.autonomy_advice,
            },
            "logs": list(self._logs[-30:]),  # alleen de staart naar browser
            "log_times": list(self._log_times[-30:]),  # parallel aan logs
        }
