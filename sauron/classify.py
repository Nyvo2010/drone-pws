"""Laag 2: classificatie — is een hotspot een (mogelijke) bosbrand?

Twee standen, omdat één drempel in de praktijk niet werkt:

  verdacht <=>  max_temp >= suspect_min_abs_c  EN
                stijging >= suspect_min_delta_c
  brand    <=>  max_temp >= fire_min_abs_c     EN
                stijging >= fire_min_delta_c

Waarom absoluut én relatief? Een bosbrand is honderden graden; een
zonverwarmde steen of een dakpan is 55-70 C, ook op een koude dag met
veel zon. Alleen naar "warmer dan de omgeving" kijken maakt daar een
brand van (dat was de valse melding op een steen). De absolute grens
weert die voorwerpen, de relatieve grens weert een heet veld waar
alles al warm is.

Daarnaast een score 0..1 voor rangschikking bij meerdere hotspots:
65% temperatuurstijging, 35% oppervlakte.

Nog NIET hier (bewust):
- RGB-bevestiging (RGB kijkt vooruit, thermal omlaag — geen overlap);
- rookdetectie op RGB.
"""

from .config import DEFAULT, Config


def _klem_0_1(waarde):
    """Klem een getal tussen 0 en 1 voor de deelscores."""
    return max(0.0, min(1.0, waarde))


def classify_hotspot(hotspot, ambient, cfg=DEFAULT):
    """Classificeer één hotspot. Retourneert dict met oordeel + uitleg.

    'level' is "fire", "suspect" of "noise". De 'reasons' maken het
    oordeel navolgbaar in het veld: de operator ziet WAAROM iets wel of
    niet als brand geldt.
    """
    if not isinstance(cfg, Config):
        raise TypeError("cfg moet een Config zijn")
    max_temp = hotspot["max_temp"]
    area = hotspot["area"]
    delta_t = max_temp - ambient
    groot = area >= cfg.min_area_pixels

    brand = (max_temp >= cfg.fire_min_abs_c
             and delta_t >= cfg.fire_min_delta_c
             and groot)
    verdacht = (max_temp >= cfg.suspect_min_abs_c
                and delta_t >= cfg.suspect_min_delta_c
                and groot)

    # Deelscores: een sprong van 1,6x de branddrempel = vol punt,
    # 12 pixels = vol punt. Kalibratieknoppen, geen natuurconstanten.
    delta_score = _klem_0_1(delta_t / (cfg.fire_min_delta_c * 1.6))
    area_score = _klem_0_1(area / 12.0)
    score = round(0.65 * delta_score + 0.35 * area_score, 3)

    return {
        "level": "fire" if brand else ("suspect" if verdacht else "noise"),
        "is_fire": bool(brand),
        "is_suspect": bool(verdacht),
        "score": score,
        "delta_t": round(delta_t, 1),
        "max_temp": round(max_temp, 1),
        "area": area,
        "reasons": {
            # Elk criterium apart zichtbaar voor de operator.
            "stijging_boven_omgeving": delta_t >= cfg.fire_min_delta_c,
            "absoluut_warm_genoeg": max_temp >= cfg.fire_min_abs_c,
            "groot_genoeg": groot,
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
