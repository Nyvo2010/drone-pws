"""Hertun de drempels op opgenomen veldframes (na de vlucht, offline).

Gebruik:
    python3 dashboard.py --capture          # vlucht met ruwe frames
    python3 -m sauron.replay logs/flight-20261020-101500.jsonl

Waarom: de drempels in config.py zijn startwaarden. Met een gewone
vluchtlog kun je ze niet meer testen zonder opnieuw te vliegen; met
--capture staat elk frame in het bestand en rekent dit script de
verschillende drempels door. Zo kies je 's avonds de waarde die op echte
data werkt.

Het script is puur lezen: het verandert niets aan de config of het log.
"""

import json
import sys
from dataclasses import replace

from . import classify, thermal
from .config import DEFAULT

# Waarden die in het veld redelijk zijn om te proberen.
DEEP_DREMPELS = (8.0, 10.0, 12.0, 15.0, 20.0)
AREA_DREMPELS = (2, 3, 5)
MAX_FRAMES = 200  # eerste 200 frames is genoeg om een drempel te kiezen


def load_frames(path):
    """Alle opgenomen ruwe frames uit één JSONL-vluchtbestand."""
    frames = []
    with open(path, encoding="utf-8") as bestand:
        for regel in bestand:
            regel = regel.strip()
            if not regel:
                continue
            try:
                item = json.loads(regel)
            except json.JSONDecodeError:
                continue  # half geschreven laatste regel na een crash
            cells = item.get("cells")
            if item.get("type") == "ingest" and isinstance(cells, list):
                frames.append(cells)
            if len(frames) >= MAX_FRAMES:
                break
    return frames


def tel_buiten_bereik(frame, cfg=DEFAULT):
    """Aantal cellen buiten het geldige temperatuurbereik (dode pixels)."""
    lo, hi = cfg.valid_temp_min_c, cfg.valid_temp_max_c
    return sum(1 for v in frame if not (lo <= v <= hi))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("gebruik: python3 -m sauron.replay <vlucht.jsonl>")
        return 2

    frames = load_frames(argv[0])
    if not frames:
        print("geen ruwe frames in dit bestand.")
        print("start de volgende vlucht met: python3 dashboard.py --capture")
        return 1

    buiten = [tel_buiten_bereik(f) for f in frames]
    print("%d frames, %d waarden per frame" % (len(frames), len(frames[0])))
    print("buiten bereik (dode/rare pixels): gemiddeld %.2f, max %d"
          % (sum(buiten) / len(buiten), max(buiten)))
    print()
    print("%-6s %-6s %-10s %-10s %s"
          % ("dT", "minpx", "frames*", "hotspots", "heetste C"))
    for dt in DEEP_DREMPELS:
        for area in AREA_DREMPELS:
            cfg = replace(DEFAULT, threshold_above_ambient=dt,
                          min_area_pixels=area)
            met_brand = 0
            hotspots = 0
            heetste = 0.0
            for frame in frames:
                ambient, _, gevonden = thermal.find_hotspots(frame, cfg)
                hotspots += len(gevonden)
                branden = classify.classify_all(gevonden, ambient, cfg)
                if branden:
                    met_brand += 1
                    heetste = max(heetste, branden[0]["max_temp"])
            print("%-6.1f %-6d %-10d %-10d %.1f"
                  % (dt, area, met_brand, hotspots, heetste))
    print("\nframes* = frames met minstens één geclassificeerde brand")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
