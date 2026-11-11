"""Laag 1: heat point identificatie uit een MLX90640-frame.

Input: 768 temperatuurwaarden (floats), rij-majeur: index = rij * 32 + kolom.
Output: lijst van hotspot-dicts, gesorteerd op max_temp (heetste eerst).

Stappen:
1. frame_to_matrix: platte lijst -> 24 rijen x 32 kolommen.
2. estimate_ambient: mediaan van het hele frame als omgevingstemperatuur.
   Mediaan (geen gemiddelde!) zodat een kleine brand de schatting niet
   omhoog trekt.
3. threshold_mask: pixels warmer dan ambient + marge.
4. connected_components: groepeer aangrenzende hete pixels tot blobs
   (4-connectiviteit, pure Python BFS — 768 cellen is triviaal klein).
5. find_hotspots: filter blobs kleiner dan min_area_pixels (ruis) en
   bereken per blob: heetste pixel, centroid en oppervlakte.

Daarnaast `assess_frame`: is dit frame überhaupt een geloofwaardig beeld
van de grond? Een sensor die net aan staat, of een mislukte read, geeft
een mediaan van 0 of 480 C. Zulke frames mogen nooit branden opleveren.

Alleen stdlib, geen numpy: werkt overal en offline.
"""

import math
from collections import deque

from .config import DEFAULT, Config


def validated_values(frame):
    """Frame -> lijst floats, of ValueError als het pakket niet klopt.

    Een kapot pakket (verkeerde lengte, tekst, None, NaN, inf) mag nooit
    stilzwijgend als "geen brand" doorgaan: de server maakt er HTTP 400
    van, zodat je in het veld ziet dat er iets mis is met de zender.
    """
    ruw = list(frame)
    if len(ruw) != DEFAULT.width * DEFAULT.height:
        raise ValueError(
            "verwacht %d waarden, kreeg %d"
            % (DEFAULT.width * DEFAULT.height, len(ruw))
        )
    try:
        values = [float(v) for v in ruw]
    except (TypeError, ValueError):
        raise ValueError("frame bevat niet-numerieke waarden")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("frame bevat NaN of oneindige waarden")
    return values


def to_matrix(values):
    """Platte lijst -> 24 rijen van 32 kolommen (rij-majeur)."""
    return [
        values[rij * DEFAULT.width:(rij + 1) * DEFAULT.width]
        for rij in range(DEFAULT.height)
    ]


def frame_to_matrix(frame):
    """Zet een plat 768-frame om naar 24 rijen van 32 kolommen."""
    return to_matrix(validated_values(frame))


def sanitize_values(values, cfg=DEFAULT):
    """Vervang onmogelijke meetwaarden door de mediaan van het frame.

    De MLX90640 heeft altijd een paar dode pixels; bij een mislukte
    I2C-read komen er ook uitschieters binnen. Zo'n cel is geen warmtebron
    maar een kapotte sensor, en mag dus nooit een brand worden. We zetten
    hem op de mediaan (dus "gewoon" omgevingstemperatuur) in plaats van
    hem weg te gooien: zo blijft de 32x24-vorm intact en blijft de pixel
    op zijn plek in het beeld staan.
    """
    lo, hi = cfg.valid_temp_min_c, cfg.valid_temp_max_c
    goed = sorted(v for v in values if lo <= v <= hi)
    if not goed or len(goed) == len(values):
        # Alles in orde (geen werk) of alles onzin (dan valt er niets te
        # vervangen); in het laatste geval blijft het gedrag zoals het was
        # en vangt assess_frame het frame als geheel af.
        return list(values)
    vervanger = goed[len(goed) // 2]
    return [v if lo <= v <= hi else vervanger for v in values]


def sanitize_frame(frame, cfg=DEFAULT):
    """Zelfde klep, maar op een plat frame (voor /api/frame en de staat)."""
    return sanitize_values(validated_values(frame), cfg)


def estimate_ambient(matrix):
    """Schatting van de omgevingstemperatuur = mediaan van het frame.

    De mediaan is ongevoelig voor een kleine hete brandvlek, terwijl een
    gemiddelde daardoor juist omhoog zou schuiven (en de brand zou
    "verstoppen" achter een te hoge drempel).
    """
    flat = sorted(v for rij in matrix for v in rij)
    midden = len(flat) // 2
    if len(flat) % 2 == 1:
        return float(flat[midden])
    return float((flat[midden - 1] + flat[midden]) / 2.0)


def assess_frame(frame, cfg=DEFAULT):
    """Is dit frame een geloofwaardig beeld van de grond?

    Retourneert (ambient, problemen) waarbij 'problemen' een lijst is met
    operator-taal. Lege lijst = frame is bruikbaar.

    Twee dingen die in het veld echt misgingen:
    - de sensor was net aangezet en gaf een mediaan van 480 C; de laptop
      meldde 137 branden in één vlucht;
    - een deel van de pixels zat op de sensorgrens (verzadigd), waardoor
      de mediaan en de drempel verschoven.
    """
    ruw = validated_values(frame)
    lo, hi = cfg.valid_temp_min_c, cfg.valid_temp_max_c
    problemen = []

    verzadigd = sum(1 for v in ruw if v >= hi)
    fractie = verzadigd / float(len(ruw))
    if fractie > cfg.max_saturated_fraction:
        problemen.append(
            "%.0f%% van de pixels zit op de sensorgrens (>= %.0f C): "
            "beeld verzadigd" % (fractie * 100.0, hi))

    matrix = to_matrix(sanitize_values(ruw, cfg))
    ambient = estimate_ambient(matrix)
    if ambient < cfg.ambient_min_c or ambient > cfg.ambient_max_c:
        problemen.append(
            "omgeving %.1f C is onwaarschijnlijk (-15..70 C): sensor niet "
            "op temperatuur of frame kapot" % ambient)
    return ambient, problemen


def threshold_mask(matrix, threshold):
    """Boolean-masker: True waar de pixel warmer is dan de drempel."""
    return [[v > threshold for v in rij] for rij in matrix]


def connected_components(mask):
    """Groepeer aangrenzende True-cellen tot blobs (4-connectiviteit).

    4-connectiviteit (boven/onder/links/rechts, geen diagonalen) is een
    bewuste keuze: diagonalen tellen niet mee, zodat twee losse warme
    pixels die elkaar alleen in een hoek raken toch twee blobs blijven.
    """
    hoogte = len(mask)
    breedte = len(mask[0])
    bezocht = [[False] * breedte for _ in range(hoogte)]
    blobs = []
    for start_y in range(hoogte):
        for start_x in range(breedte):
            # Sla over wat niet heet is of al bij een blob hoort.
            if not mask[start_y][start_x] or bezocht[start_y][start_x]:
                continue
            # BFS vanaf dit startpunt: alles wat eraan vastzit hoort erbij.
            blob = []
            wachtrij = deque([(start_x, start_y)])
            bezocht[start_y][start_x] = True
            while wachtrij:
                x, y = wachtrij.popleft()
                blob.append((x, y))
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < breedte and 0 <= ny < hoogte:
                        if mask[ny][nx] and not bezocht[ny][nx]:
                            bezocht[ny][nx] = True
                            wachtrij.append((nx, ny))
            blobs.append(blob)
    return blobs


def _beschrijf_blob(blob, matrix):
    """Vat één blob samen: heetste pixel, centroid en oppervlakte."""
    # Heetste pixel van deze blob (x = kolom, y = rij).
    hx, hy = max(blob, key=lambda p: matrix[p[1]][p[0]])
    # Centroid = gemiddelde positie van alle pixels in de blob. Bij een
    # grote brand is dit stabieler dan één enkele heetste pixel.
    n = len(blob)
    cx = sum(p[0] for p in blob) / n
    cy = sum(p[1] for p in blob) / n
    return {
        "max_temp": float(matrix[hy][hx]),
        "x": hx,  # kolom van heetste pixel (0-31)
        "y": hy,  # rij van heetste pixel (0-23)
        "centroid_x": cx,
        "centroid_y": cy,
        "area": n,  # aantal pixels boven de drempel
    }


def find_hotspots(frame, cfg=DEFAULT):
    """Hoofdfunctie laag 1: frame -> (ambient, threshold, hotspots).

    Retourneert een tuple (ambient, threshold, hotspots) waarbij hotspots
    een lijst is van blob-dicts, gesorteerd op max_temp (heetste eerst).
    Lege lijst = geen enkele blob groot genoeg = geen hotspot.
    """
    if not isinstance(cfg, Config):
        raise TypeError("cfg moet een Config zijn")
    matrix = to_matrix(sanitize_values(validated_values(frame), cfg))
    ambient = estimate_ambient(matrix)
    threshold = ambient + cfg.threshold_above_ambient
    mask = threshold_mask(matrix, threshold)
    hotspots = [
        _beschrijf_blob(blob, matrix)
        for blob in connected_components(mask)
        if len(blob) >= cfg.min_area_pixels  # ruis wegfilteren
    ]
    # Heetste eerst: de operator kijkt eerst naar de grootste dreiging.
    hotspots.sort(key=lambda h: h["max_temp"], reverse=True)
    return ambient, threshold, hotspots
