"""Gesimuleerde MLX90640-frames voor demo, dashboard en tests.

Eén plek voor nep-data, zodat main_demo, dashboard en tests nooit elk hun
eigen generator hebben (niet overbodig). Nooit gebruiken in productie:
echte frames komen straks via POST /api/ingest van de ESP32-forwarder.
"""

import math
import random

from .config import DEFAULT


def make_frame(ambient=22.0, vlekken=(), ruis=0.4, seed=1):
    """Bouw een nep-frame: 768 floats, rij-majeur (32 kolommen x 24 rijen).

    'vlekken' = lijst van (x, y, piek_temp, straal_px). Elke vlek is een
    gaussische heuvel: heet in het midden, vloeiend kouder naar buiten —
    zoals een echte brand er op lage resolutie uitziet. 'ruis' is de
    sensorruis rond de omgevingstemperatuur.
    """
    rng = random.Random(seed)
    frame = []
    for rij in range(DEFAULT.height):
        for kolom in range(DEFAULT.width):
            temp = ambient + rng.uniform(-ruis, ruis)
            for vx, vy, piek, straal in vlekken:
                afstand2 = (kolom - vx) ** 2 + (rij - vy) ** 2
                temp += (piek - ambient) * math.exp(-afstand2 / (straal ** 2))
            frame.append(temp)
    return frame
