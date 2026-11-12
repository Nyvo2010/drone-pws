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

from .config import DEFAULT, Config, groot_genoeg


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


def _grote_hete_regio(values, cfg=DEFAULT):
    """Indices van aaneengesloten cellen boven de sensorgrens.

    Eén losse 565 C of een cluster van drie is een leesfout (zo kwamen ze
    op 30 okt binnen). Maar een echt vuur dichtbij is heter dan de sensor
    kan uitdrukken: op 11 nov stond er 640 C in een frame met een vlam van
    tientallen pixels. Zo'n groep is geen kapotte pixel. Alleen groepen
    vanaf `min_saturated_pixels` cellen tellen als "heter dan de sensor";
    de rest blijft ruis en wordt door de mediaan vervangen.
    """
    hi = cfg.valid_temp_max_c
    heet = {i for i, v in enumerate(values) if v > hi}
    if len(heet) < cfg.min_saturated_pixels:
        return set()
    breedte, hoogte = cfg.width, cfg.height
    gezien = set()
    groot = set()
    for start in heet:
        if start in gezien:
            continue
        groep = []
        wachtrij = [start]
        gezien.add(start)
        while wachtrij:
            i = wachtrij.pop()
            groep.append(i)
            x, y = i % breedte, i // breedte
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if not (0 <= nx < breedte and 0 <= ny < hoogte):
                    continue
                j = ny * breedte + nx
                if j in heet and j not in gezien:
                    gezien.add(j)
                    wachtrij.append(j)
        if len(groep) >= cfg.min_saturated_pixels:
            groot.update(groep)
    return groot


def sanitize_values(values, cfg=DEFAULT):
    """Vervang onmogelijke meetwaarden door de mediaan van het frame.

    De MLX90640 heeft altijd een paar dode pixels; bij een mislukte
    I2C-read komen er ook uitschieters binnen. Zo'n cel is geen warmtebron
    maar een kapotte sensor, en mag dus nooit een brand worden. We zetten
    hem op de mediaan (dus "gewoon" omgevingstemperatuur) in plaats van
    hem weg te gooien: zo blijft de 32x24-vorm intact en blijft de pixel
    op zijn plek in het beeld staan.

    Uitzondering: een groot aaneengesloten gebied boven de sensorgrens is
    een bron heter dan de sensor aankan, geen leesfout. Dat klemmen we op
    `valid_temp_max_c` in plaats van het weg te poetsen; anders zou de
    heetste frame van een echte brand (640 C) als leeg veld doorgaan.
    """
    lo, hi = cfg.valid_temp_min_c, cfg.valid_temp_max_c
    goed = sorted(v for v in values if lo <= v <= hi)
    if not goed or len(goed) == len(values):
        # Alles in orde (geen werk) of alles onzin (dan valt er niets te
        # vervangen); in het laatste geval blijft het gedrag zoals het was
        # en vangt assess_frame het frame als geheel af.
        return list(values)
    vervanger = goed[len(goed) // 2]
    heet = _grote_hete_regio(values, cfg)
    return [v if lo <= v <= hi else (hi if i in heet else vervanger)
            for i, v in enumerate(values)]


def sanitize_frame(frame, cfg=DEFAULT):
    """Zelfde klep, maar op een plat frame (voor /api/frame en de staat)."""
    return sanitize_values(validated_values(frame), cfg)


def _mediaan(waarden):
    """Mediaan van een lijst getallen (ook gebruikt voor de lokale ring)."""
    flat = sorted(waarden)
    if not flat:
        return None
    midden = len(flat) // 2
    if len(flat) % 2 == 1:
        return float(flat[midden])
    return float((flat[midden - 1] + flat[midden]) / 2.0)


def estimate_ambient(matrix):
    """Schatting van de omgevingstemperatuur = mediaan van het frame.

    De mediaan is ongevoelig voor een kleine hete brandvlek, terwijl een
    gemiddelde daardoor juist omhoog zou schuiven (en de brand zou
    "verstoppen" achter een te hoge drempel).
    """
    return _mediaan(v for rij in matrix for v in rij)


def local_background(matrix, cellen, cfg=DEFAULT):
    """Mediaan en ruis van de ring cellen rond een blob.

    Dit is de vergelijking met "de dingen eromheen": de ring begint één
    cel buiten de blob, zodat de wazige rand van de vlam de referentie
    niet opwarmt. Een klein vuur heeft koude grond naast zich; een groot
    zonverwarmd dak heeft een ring die net zo warm is als het dak zelf.
    Daardoor zegt de lokale sprong meer over een vlam dan de mediaan van
    het hele frame.

    Retourneert (mediaan, sigma, n). (None, None, n) als er te weinig
    ring overblijft (blob tegen de beeldrand).
    """
    hoogte, breedte = len(matrix), len(matrix[0])
    straal = max(1, cfg.local_ring_px)
    xs = [x for x, _ in cellen]
    ys = [y for _, y in cellen]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    waarden = []
    for y in range(max(0, y0 - straal), min(hoogte, y1 + straal + 1)):
        for x in range(max(0, x0 - straal), min(breedte, x1 + straal + 1)):
            if x0 - 1 <= x <= x1 + 1 and y0 - 1 <= y <= y1 + 1:
                continue
            waarden.append(matrix[y][x])
    if len(waarden) < 6:
        return None, None, len(waarden)
    achtergrond = _mediaan(waarden)
    afwijking = _mediaan([abs(v - achtergrond) for v in waarden])
    return achtergrond, 1.4826 * afwijking, len(waarden)


def _grow_mask(mask, radius):
    """Verdik een masker met `radius` cellen (Chebyshev).

    Alleen voor het groeperen: twee hete cellen met een koud gat ertussen
    (rook, één cel net onder de drempel) horen bij dezelfde vlam. Op
    15:35 werden drie losse cellen van 328/185/79 C anders drie tracks van
    één pixel, die elk na één frame verdwenen en nooit bevestigd werden.
    """
    if radius <= 0:
        return [rij[:] for rij in mask]
    hoogte, breedte = len(mask), len(mask[0])
    uit = [[False] * breedte for _ in range(hoogte)]
    for y in range(hoogte):
        for x in range(breedte):
            if not mask[y][x]:
                continue
            for ny in range(max(0, y - radius), min(hoogte, y + radius + 1)):
                rij = uit[ny]
                for nx in range(max(0, x - radius),
                                min(breedte, x + radius + 1)):
                    rij[nx] = True
    return uit


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


def _beschrijf_blob(blob, matrix, cfg=DEFAULT):
    """Vat één blob samen: heetste pixel, centroid, oppervlakte en contrast."""
    waarden = [matrix[y][x] for x, y in blob]
    # Heetste pixel van deze blob (x = kolom, y = rij).
    hx, hy = max(blob, key=lambda p: matrix[p[1]][p[0]])
    # Centroid = gemiddelde positie van alle pixels in de blob. Bij een
    # grote brand is dit stabieler dan één enkele heetste pixel.
    n = len(blob)
    cx = sum(p[0] for p in blob) / n
    cy = sum(p[1] for p in blob) / n
    max_temp = float(matrix[hy][hx])
    gemiddelde = sum(waarden) / n
    achtergrond, sigma, ring_n = local_background(matrix, blob, cfg)
    return {
        "max_temp": max_temp,
        "x": hx,  # kolom van heetste pixel (0-31)
        "y": hy,  # rij van heetste pixel (0-23)
        "centroid_x": cx,
        "centroid_y": cy,
        "area": n,  # aantal pixels boven de drempel
        # Vorm van de vlam: hete kern boven een vlakker wordende vlek.
        # Een zonverwarmde steen is vlak (contrast ~0-3 C), een vlam niet.
        "core_contrast": round(max_temp - gemiddelde, 1),
        # Vergelijking met de grond direct rond de blob. Dit is de
        # hoogte-onafhankelijke maat: de vlam zakt in absolute waarde als
        # hij kleiner wordt, maar blijft heter dan zijn omgeving.
        "local_bg": None if achtergrond is None else round(achtergrond, 1),
        "local_delta": (None if achtergrond is None
                        else round(max_temp - achtergrond, 1)),
        "local_sigma": None if sigma is None else round(sigma, 2),
        "local_ring_n": ring_n,
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
    # Eerst gaten dichten (rook, één cel net onder de drempel), daarna pas
    # blobs tellen. De statistiek blijft over de écht hete cellen gaan.
    hotspots = []
    for groep in connected_components(_grow_mask(mask, cfg.blob_merge_radius)):
        blob = [(x, y) for x, y in groep if mask[y][x]]
        if not blob:
            continue
        info = _beschrijf_blob(blob, matrix, cfg)
        # Grootte filtert ruis, maar een cel die ver boven de omgeving
        # uitkomt telt altijd mee (één pixel vlam op hoogte).
        if groot_genoeg(info["area"], info["max_temp"], cfg, ambient):
            hotspots.append(info)
    # Heetste eerst: de operator kijkt eerst naar de grootste dreiging.
    hotspots.sort(key=lambda h: h["max_temp"], reverse=True)
    return ambient, threshold, hotspots
