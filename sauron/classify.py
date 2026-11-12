"""Laag 2: classificatie — is een hotspot een (mogelijke) bosbrand?

Drie routes naar "brand", omdat één drempel in de praktijk niet werkt:

  verdacht <=>  stijging >= suspect_delta_c (globaal OF lokaal)
  brand    <=>  stijging >= fire_delta_c
             OF  (max_temp >= fire_min_abs_c EN
                  stijging >= fire_min_abs_delta_c)
             OF  (lokale sprong >= fire_local_delta_c EN
                  max_temp >= fire_local_abs_c EN
                  hete kern (vanaf 3 cellen))

Waarom relatief en niet absoluut? Een brand is niet "warmer dan een
vaste temperatuur", maar heter dan de grond eromheen. De absolute waarde
hangt af van de vlieghoogte (een vlam die een halve pixel vult leest
lager), van rook en van de luchttemperatuur; de sprong boven de omgeving
blijft. Velddata 11 nov (brand op 1 m): 49-116 C gemeten, 44-105 C sprong,
en met een 90 C-grens bleef 34 frames van een echte brand "verdacht".

Waarom dan toch een absolute tweede weg? Dichtbij vult een vlam de pixel
en is de absolute waarde zelf hoog; die weg vangt een vuur in een al heet
veld, waar de relatieve sprong minder ruimte heeft. Hij is nooit de
hoofdregel: een zonverwarmde steen van 43 C bij 26 C omgeving (de valse
melding van 30 okt) heeft een sprong van 17 C en blijft "ruis".

Waarom de derde weg (lokaal)? De mediaan van het hele frame is een
grove omgeving en de vaste +60 C grens ligt op hoogte te hoog: in de
vlucht van 14:50 stond een echte brand 25 s lang op 45-66 C (+38 tot
+59 boven de omgeving) en werd pas "brand" op het moment dat de drone
laag genoeg hing. De ring direct rond de vlam is de grond naast hem, en
die blijft koud. Een vlam heeft bovendien een hete kern (heetste cel
flink boven het gemiddelde van de vlek); een zonverwarmde steen, dakpan
of asfaltvlak is juist vlak van temperatuur. Samen houdt dat passieve
oppervlakken buiten en telt een vlam die maar één cel vult toch mee.

Daarnaast een score 0..1 voor rangschikking bij meerdere hotspots:
65% temperatuurstijging, 35% oppervlakte.

Nog NIET hier (bewust):
- RGB-bevestiging (RGB kijkt vooruit, thermal omlaag — geen overlap);
- rookdetectie op RGB.
"""

from .config import DEFAULT, Config, groot_genoeg


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
    # Zonder ring (bijv. een handmatige hotspot in een test) valt de lokale
    # maat terug op de globale sprong; er wordt niets verzonnen.
    local_delta = hotspot.get("local_delta")
    if local_delta is None:
        local_delta = delta_t
    core_contrast = hotspot.get("core_contrast")
    # Zelfde regel als in thermal.find_hotspots: groot, of een sprong die
    # alleen een vlam maakt (één pixel op hoogte telt dus mee).
    groot = groot_genoeg(area, max_temp, cfg, ambient)

    # Hoofdregel: de sprong boven de omgeving. Onafhankelijk van hoogte,
    # rook en luchttemperatuur; een vlam die een halve pixel vult zakt in
    # absolute waarde maar houdt zijn sprong.
    vuur_relatief = delta_t >= cfg.fire_delta_c
    # Tweede weg: dichtbij vult de vlam de pixel, dus de absolute waarde is
    # zelf hoog. Vangt een vuur in een veld dat al warm is (lucht 40 C).
    heet_absoluut = (max_temp >= cfg.fire_min_abs_c
                     and delta_t >= cfg.fire_min_abs_delta_c)
    # Derde weg: lokale sprong tegen de grond naast de vlam. Dit is de
    # route die op hoogte blijft werken, want de vlam zakt in absolute
    # waarde maar niet onder zijn eigen omgeving.
    lokaal = local_delta >= cfg.fire_local_delta_c
    # Vanaf 3 cellen moet de vlek een hete kern hebben (vlam), niet vlak
    # zijn zoals een zonverwarmde steen. Bij 1-2 cellen is er geen vorm te
    # meten en telt de lokale sprong alleen.
    kern = area <= 2 or (core_contrast is not None
                         and core_contrast >= cfg.fire_core_contrast_c)
    vuur_lokaal = bool(lokaal and kern and max_temp >= cfg.fire_local_abs_c)
    brand = bool(((vuur_relatief or heet_absoluut) and groot) or vuur_lokaal)
    verdacht = bool((delta_t >= cfg.suspect_delta_c
                     or local_delta >= cfg.suspect_delta_c) and groot)

    # Deelscores: een sprong van 1,6x de branddrempel = vol punt,
    # 12 pixels = vol punt. Kalibratieknoppen, geen natuurconstanten.
    sprong = max(delta_t, local_delta)
    delta_score = _klem_0_1(sprong / (cfg.fire_delta_c * 1.6))
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
            "sprong_boven_omgeving": bool(vuur_relatief),
            "absoluut_heet": bool(heet_absoluut),
            "lokale_sprong": bool(vuur_lokaal),
            "hete_kern": bool(area >= 3 and core_contrast is not None
                              and core_contrast >= cfg.fire_core_contrast_c),
            "geen_ruis": bool(groot),
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
