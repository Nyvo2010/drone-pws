"""Dunne lijm: frame + GPS -> compleet detectieresultaat.

Eén functie, geen I/O: alle hardwarepraat (WiFi, serieel, camera) blijft
buiten dit pakket bij de teamgenoot / main_demo. Daardoor is de hele
keten testbaar met gesimuleerde lijsten.

Volgorde = de drie teamstappen:
1. thermal.find_hotspots  (laag 1: grootste warmtepunten)
2. classify.classify_all   (laag 2: is het een bosbrand? + meerdere)
3. geo.locate_hotspot      (per brand: echte coördinaten via hoogte +
                           pixelverschuiving + heading)

Locatie is een voorrecht, geen recht: zonder bruikbare hoogte, zonder
geldige dronepositie of met een te zwakke GPS-fix melden we de brand wél,
maar verzinnen we geen coördinaten. Dat is in het veld het verschil
tussen "geen brand" en "brand, locatie onbekend".
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


def _location_blocker(lat, lon, agl, gps_fix):
    """Waarom er géén locatie berekend kan worden (None = wel berekenen)."""
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


def detect_event(frame, drone_lat, drone_lon, heading_deg,
                 gps_alt_now, gps_alt_launch, gps_fix=None, cfg=DEFAULT):
    """Verwerk één meetmoment. Retourneert een plat dict (JSON-klaar).

    - 'fires' bevat alleen geclassificeerde branden, elk verrijkt met
      locatie (hotspot_lat/lon, afstand) als die te berekenen is.
    - 'hotspots' bevat ALLE blobs (ook afgekeurde) voor diagnose.
    - 'location_warning' legt uit waarom coördinaten ontbreken.
    - Ontbrekende hoogte (gps_alt_now/launch None) is geen crash: AGL
      wordt None en de brand komt zonder locatie in de lijst.
    """
    ambient, threshold, hotspots = thermal.find_hotspots(frame, cfg)

    if gps_alt_now is None or gps_alt_launch is None:
        agl = None
    else:
        agl = geo.agl_from_gps(gps_alt_now, gps_alt_launch)

    heading = 0.0 if heading_deg is None else float(heading_deg)
    fires = classify.classify_all(hotspots, ambient, cfg)
    warning = _location_blocker(drone_lat, drone_lon, agl, gps_fix)
    for brand in fires:
        if warning is not None:
            brand.update({"hotspot_lat": None, "hotspot_lon": None,
                          "afstand_m": None})
            continue
        # Pixel van de heetste cel bepaalt de kijkrichting (centroid is
        # voor grote branden stabieler, maar de heetste pixel is de
        # interessantste plek voor de operator).
        brand.update(geo.locate_hotspot(
            drone_lat, drone_lon, heading, agl,
            brand["x"], brand["y"], cfg,
        ))

    return {
        "ambient": round(ambient, 1),
        "threshold": round(threshold, 1),
        "agl_m": None if agl is None else round(agl, 1),
        "height_warning": None if agl is None else geo.check_height(agl, cfg),
        "location_warning": warning,
        "n_hotspots": len(hotspots),
        "n_fires": len(fires),
        "hotspots": hotspots,
        "fires": fires,
    }
