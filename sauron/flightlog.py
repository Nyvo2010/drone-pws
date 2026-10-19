"""Vluchtregistratie: één JSONL-bestand per vlucht, lokaal op de laptop.

Waarom JSONL en niet één groot JSON-document? Elke regel wordt direct
geflusht, dus een crash of stroomverlies kost hooguit de laatste regel.
Achteraf lees je het bestand regel voor regel, of je opent het in een
editor/script. De webserver kan het ook downloaden via /api/flights.

Regeltypen:
- flight_start  {flight, config}
- log           {message}
- ingest        {drone, thermal, hotspots, fires, warning} (+ cells bij --capture)
- fire_new / fire_lost / fire_reacquired / fire_archived {fire}
- flight_end    {reason}

`fire` bevat altijd de volledige laatste detectie (temperatuur, score,
coördinaten, reasons) plus id, first_seen, last_seen en observations.
"""

import json
import re
import threading
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .config import DEFAULT

_NAME_RE = re.compile(r"flight-\d{8}-\d{6}(?:-\d+)?\.jsonl\Z")


class FlightRecorder:
    """Schrijft append-only JSONL naar `directory`; één open vlucht tegelijk."""

    def __init__(self, directory="logs", cfg=DEFAULT, capture_frames=False):
        self.directory = Path(directory)
        self.cfg = cfg
        # True = ook het ruwe 768-punts frame per ingest bewaren (~5 kB per
        # regel). Daarmee kun je na de vlucht drempels hertunen op echte
        # velddata i.p.v. opnieuw te moeten vliegen.
        self.capture_frames = capture_frames
        self._fh = None
        self._flight = None
        self._lock = threading.Lock()

    @property
    def flight(self):
        return dict(self._flight) if self._flight else None

    def start(self):
        """Sluit een eventueel open vlucht en begin een nieuwe."""
        with self._lock:
            self._close_locked("nieuwe vlucht")
            self.directory.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path = self.directory / ("flight-%s.jsonl" % stamp)
            volgnummer = 2
            while path.exists():
                path = self.directory / ("flight-%s-%d.jsonl" % (stamp, volgnummer))
                volgnummer += 1
            self._fh = open(path, "a", encoding="utf-8")
            self._flight = {
                # Uniek per bestand, ook als twee vluchten in dezelfde
                # seconde starten (dan komt er -2 achter).
                "id": path.stem[len("flight-"):],
                "file": str(path),
                "started": time.time(),
            }
            self._write_locked({
                "type": "flight_start",
                "t": self._flight["started"],
                "flight": dict(self._flight),
                "config": asdict(self.cfg),
            })
            return dict(self._flight)

    def record(self, event, t=None):
        """Voeg één regel toe; doet niets als er geen vlucht open is."""
        with self._lock:
            payload = {"t": time.time() if t is None else float(t)}
            payload.update(event)
            self._write_locked(payload)

    def end(self, reason="gestopt"):
        """Schrijf flight_end en sluit het bestand."""
        with self._lock:
            self._close_locked(reason)

    def _close_locked(self, reason):
        if self._fh is None:
            return
        self._write_locked({"type": "flight_end", "reason": reason})
        self._fh.close()
        self._fh = None

    def _write_locked(self, obj):
        if self._fh is None:
            return
        self._fh.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()

    def list_flights(self):
        """Beschikbare vluchtbestanden, nieuwste eerst."""
        if not self.directory.is_dir():
            return []
        items = []
        for path in self.directory.glob("flight-*.jsonl"):
            if not _NAME_RE.match(path.name):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            items.append({
                "name": path.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
        items.sort(key=lambda item: item["modified"], reverse=True)
        return items

    def path_for(self, name):
        """Veilig pad voor één bestandsnaam (geen paden of `..`)."""
        name = str(name)
        if not _NAME_RE.match(name):
            return None
        path = self.directory / name
        return path if path.is_file() else None
