"""Dunne lijm: frame + GPS -> compleet detectieresultaat.

Eén functie, geen I/O: alle hardwarepraat (WiFi, serieel, camera) blijft
buiten dit pakket bij de teamgenoot / main_demo. Daardoor is de hele
keten testbaar met gesimuleerde lijsten.

Volgorde = de drie teamstappen:
1. thermal.assess_frame   (is dit frame bruikbaar? sensor op temperatuur?)
2. thermal.find_hotspots  (laag 1: grootste warmtepunten)
3. classify               (laag 2: brand, verdacht of ruis)
4. geo.locate_hotspot     (per brand: echte coördinaten via hoogte +
                           pixelverschuiving + heading)

Locatie is een voorrecht, geen recht: zonder bruikbare hoogte, zonder
geldige dronepositie of met een te zwakke GPS-fix melden we de brand wél,
maar verzinnen we geen coördinaten. Dat is in het veld het verschil
tussen "geen brand" en "brand, locatie onbekend".

Een onbruikbaar frame (sensor net aan, verzadigd beeld) levert NOOIT een
brand op: de temperaturen zijn dan geen meting. De operator ziet de
waarschuwing en de hotspots als diagnose, geen alarmering.
"""

import math

from . import classify, geo, thermal
from .config import DEFAULT

# Fixkwaliteit onder dit nummer heeft geen betrouwbare 3D-positie
# (0 = geen fix, 1 = 2D: wel lat/lon, geen hoogte).
MIN_FIX_FOR_LOCATION = 2


def _valid_position(lat, lon):
    """True als (lat, lon) een echte dronepositie kan zijn.

    De ESP32 stuurt bij een ontbrekende fix vaak 0.0/0.0. Dat is een
    geldig getal maar geen positie; coördinaten bij de Gulf of Guinea
    zouden de operator alleen maar op het verkeerde been zetten.
    """
    if lat is None or lon is None:
        return False
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    return not (lat == 0.0 and lon == 0.0)


def _location_blocker(lat, lon, agl, gps_fix, position_age_s=None,
                      cfg=DEFAULT):
    """Waarom er géén locatie berekend kan worden (None = wel berekenen)."""
    if position_age_s is not None:
        try:
            ouder = float(position_age_s)
        except (TypeError, ValueError):
            ouder = None
        if ouder is not None and ouder > cfg.max_position_age_s:
            # Op een zwakke link komt het warmtebeeld door terwijl /api/gps
            # wegvalt. De oude positie blijft in beeld (met leeftijd, zie
            # drone.gps_age_s), maar levert geen coördinaten meer op: die
            # zouden niet meer kloppen. De tekst is bewust constant (geen
            # seconden erin): anders verandert de waarschuwing elk frame en
            # loopt het logboek vol met dezelfde regel.
            return "geen locatie: positie te oud (GPS valt weg)"
    if agl is None:
        return "geen locatie: hoogte ontbreekt (GPS nog geen 3D-fix)"
    if agl <= 0:
        return "geen locatie: AGL %.1f m (drone niet boven lanceerpunt)" % agl
    if not _valid_position(lat, lon):
        return ("geen locatie: ongeldige dronepositie (%s, %s)"
                % (lat, lon))
    if gps_fix is not None and gps_fix < MIN_FIX_FOR_LOCATION:
        return ("geen locatie: GPS-fix te zwak (fix %s, sats nodig voor 3D)"
                % gps_fix)
    return None


def _locatie_pixel(brand):
    """Kijkrichting van een brand: centroid (stabiel) of heetste cel.

    De heetste cel verspringt bij een vlam makkelijk een paar cellen
    tussen twee frames; op 15 m AGL is dat meters. Het centroid van de
    hele blob is dezelfde brand met minder ruis, dus die gebruiken we
    voor de coördinaten (de UI markeert nog steeds de heetste cel).
    """
    x = brand.get("centroid_x")
    y = brand.get("centroid_y")
    if x is None or y is None:
        return brand["x"], brand["y"]
    return x, y


def detect_event(frame, drone_lat, drone_lon, heading_deg,
                 gps_alt_now, gps_alt_launch, gps_fix=None,
                 position_age_s=None, agl_m=None, cfg=DEFAULT):
    """Verwerk één meetmoment. Retourneert een plat dict (JSON-klaar).

    - 'fires' bevat alleen geclassificeerde branden, elk verrijkt met
      locatie (hotspot_lat/lon, afstand) als die te berekenen is.
    - 'hotspots' bevat ALLE blobs met hun oordeel (brand/verdacht/ruis),
      voor diagnose en voor de "waarom" in de UI.
    - 'sensor_warning' legt uit waarom een frame onbruikbaar is.
    - 'location_warning' legt uit waarom coördinaten ontbreken.
    - Ontbrekende hoogte (gps_alt_now/launch None) is geen crash: AGL
      wordt None en de brand komt zonder locatie in de lijst.
    - `agl_m` overschrijft de ruwe GPS-berekening: de server geeft hier
      de gedempte hoogte boven de grond uit `geo.HeightReference`, omdat
      GPS-hoogte enkele meters ruist en AGL daar direct van afhangt.
    """
    ambient, problemen = thermal.assess_frame(frame, cfg)
    _, threshold, hotspots = thermal.find_hotspots(frame, cfg)

    if agl_m is not None:
        agl = float(agl_m)
    elif gps_alt_now is None or gps_alt_launch is None:
        agl = None
    else:
        agl = geo.agl_from_gps(gps_alt_now, gps_alt_launch)

    heading = 0.0 if heading_deg is None else float(heading_deg)
    # Montage-offset van de warmtecamera t.o.v. het kompas (config).
    heading = (heading + cfg.heading_offset_deg) % 360.0

    beoordeeld = [
        {**hotspot, **classify.classify_hotspot(hotspot, ambient, cfg)}
        for hotspot in hotspots
    ]
    fires = [] if problemen else [dict(b) for b in beoordeeld
                                  if b["level"] == "fire"]

    warning = _location_blocker(drone_lat, drone_lon, agl, gps_fix,
                                position_age_s, cfg)
    for brand in fires:
        if warning is not None:
            brand.update({"hotspot_lat": None, "hotspot_lon": None,
                          "afstand_m": None})
            continue
        # Centroid bepaalt de kijkrichting: stabieler dan de heetste cel
        # en bij een grote brand precies het midden van het vuur.
        x, y = _locatie_pixel(brand)
        brand.update(geo.locate_hotspot(
            drone_lat, drone_lon, heading, agl, x, y, cfg,
        ))

    return {
        "ambient": round(ambient, 1),
        "threshold": round(threshold, 1),
        "agl_m": None if agl is None else round(agl, 1),
        "height_warning": None if agl is None else geo.check_height(agl, cfg),
        "location_warning": warning,
        "sensor_warning": ("sensor: " + "; ".join(problemen)
                           if problemen else None),
        "n_hotspots": len(hotspots),
        "n_fires": len(fires),
        "n_suspects": sum(1 for b in beoordeeld if b["level"] == "suspect"),
        "hotspots": beoordeeld,
        "fires": fires,
    }
