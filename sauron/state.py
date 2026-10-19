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
    MAX_LOGS: int = 50

    def add_log(self, bericht):
        """Voeg een regel toe; oudste valt weg bij > MAX_LOGS."""
        self._logs.append(bericht)
        if len(self._logs) > self.MAX_LOGS:
            del self._logs[:len(self._logs) - self.MAX_LOGS]

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
                "n_fires": len(self.fires),
            },
            "fires": self.fires,
            "battery": self.battery,  # None -> UI toont placeholder
            "mode": self.mode,
            "rgb_url": self.rgb_url,
            "autonomy": {
                "enabled": self.autonomy_enabled,
                "advice": self.autonomy_advice,
            },
            "logs": list(self._logs[-30:]),  # alleen de staart naar browser
        }
