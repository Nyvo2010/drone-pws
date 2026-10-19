"""Laag 2: classificatie — is een hotspot een mogelijke bosbrand?

Regel (bewust simpel gehouden, YAGNI):
  brand  <=>  (stijging boven omgeving >= fire_min_delta)
          EN  (absolute temperatuur >= fire_min_abs)
          EN  (oppervlakte >= min_area_pixels, al gefilterd in laag 1)

Daarnaast een score 0..1 voor rangschikking bij meerdere hotspots
("misschien meerderen"): 65% temperatuurstijging, 35% oppervlakte.

Nog NIET hier (bewust uitgesteld tot veldtesten):
- tijdsconsistentie over frames (nu per frame onafhankelijk);
- RGB-bevestiging (RGB kijkt vooruit, thermal omlaag — geen overlap).
"""

from .config import DEFAULT, Config


def _klem_0_1(waarde):
    """Klem een getal tussen 0 en 1 voor de deelscores."""
    return max(0.0, min(1.0, waarde))


def classify_hotspot(hotspot, ambient, cfg=DEFAULT):
    """Classificeer één hotspot. Retourneert dict met oordeel + uitleg.

    De 'reasons' maken het oordeel navolgbaar in het veld: de operator
    ziet WAAROM iets als brand is gemarkeerd (of juist niet).
    """
    if not isinstance(cfg, Config):
        raise TypeError("cfg moet een Config zijn")
    max_temp = hotspot["max_temp"]
    area = hotspot["area"]
    delta_t = max_temp - ambient

    # Deelscores: 25 graden stijging = vol punt, 12 pixels = vol punt.
    # Deze noemers zijn kalibratieknoppen, geen natuurconstanten.
    delta_score = _klem_0_1(delta_t / 25.0)
    area_score = _klem_0_1(area / 12.0)
    score = round(0.65 * delta_score + 0.35 * area_score, 3)

    warm_genoeg = delta_t >= cfg.fire_min_delta
    absoluut_warm = max_temp >= cfg.fire_min_abs
    groot_genoeg = area >= cfg.min_area_pixels

    return {
        "is_fire": bool(warm_genoeg and absoluut_warm and groot_genoeg),
        "score": score,
        "delta_t": round(delta_t, 1),
        "max_temp": round(max_temp, 1),
        "area": area,
        "reasons": {
            # Elk criterium apart zichtbaar voor de operator.
            "stijging_boven_omgeving": warm_genoeg,
            "absoluut_warm_genoeg": absoluut_warm,
            "groot_genoeg": groot_genoeg,
        },
    }


def classify_all(hotspots, ambient, cfg=DEFAULT):
    """Classificeer alle hotspots; retourneert alleen de branden.

    Niet-branden vallen weg (ze blijven wel in de pipeline-output onder
    'hotspots' staan voor diagnose). Volgorde: heetste brand eerst.
    """
    branden = []
    for hotspot in hotspots:
        oordeel = classify_hotspot(hotspot, ambient, cfg)
        if oordeel["is_fire"]:
            # Voeg positie-info toe zodat geo.py direct verder kan.
            branden.append({**hotspot, **oordeel})
    branden.sort(key=lambda b: b["max_temp"], reverse=True)
    return branden
