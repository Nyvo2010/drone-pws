"""Lokale logging: alles wat het dashboard doet komt in `logs/` terecht.

Drie sporen, elk met een eigen doel:

- `logs/flight-*.jsonl`  de data: elk frame, elke meting, elke beslissing
                         (zie flightlog.py). Bedoeld voor analyse achteraf.
- `logs/dashboard-*.log` het verhaal: start, verbinding, camera, link-
                         statistieken, fouten en elke logregel uit de UI.
                         Eén bestand per dag, append-only.
- stdout                 hetzelfde als het logbestand, voor in de terminal.

Zonder dit bestand was een mislukte vlucht alleen achteraf te raden: de
terminal was leeg en het vluchtbestand begon pas bij het eerste frame.
"""

import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%H:%M:%S"


def setup(directory="logs", level=logging.INFO, console=True):
    """Configureer root-logging naar `<directory>/dashboard-YYYYMMDD.log`.

    Geeft het pad van het logbestand terug. Idempotent: een tweede aanroep
    (bv. in een test) vervangt de handlers in plaats van ze te stapelen.
    """
    pad = Path(directory)
    pad.mkdir(parents=True, exist_ok=True)
    bestand = pad / ("dashboard-%s.log" % datetime.now().strftime("%Y%m%d"))

    formatter = logging.Formatter(_FMT, datefmt=_DATEFMT)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # pragma: no cover - defensief
            pass

    file_handler = logging.FileHandler(bestand, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    return bestand


def install_excepthooks(log=None):
    """Log onafgevangen fouten in plaats van ze alleen te printen.

    Een crash in de poll-thread werd eerder door Python op stderr gezet,
    wat in een terminal die je sluit verdwijnt. Zo staat hij in het
    logbestand en zie je achteraf waaróm de link stopte.
    """
    log = log or logging.getLogger("sauron")

    def hook(exc_type, exc_value, tb):
        log.critical("onafgevangen fout", exc_info=(exc_type, exc_value, tb))

    def thread_hook(args):
        log.critical("fout in achtergrondthread",
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = hook
    threading.excepthook = thread_hook
