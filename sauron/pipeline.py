"""Dunne lijm: frame + GPS -> compleet detectieresultaat.

Eén functie, geen I/O: alle hardwarepraat (WiFi, serieel, camera) blijft
buiten dit pakket bij de teamgenoot / main_demo. Daardoor is de hele
keten testbaar met gesimuleerde lijsten.

Volgorde = de drie teamstappen:
1. thermal.find_hotspots  (laag 1: grootste warmtepunten)
2. classify.classify_all   (laag 2: is het een bosbrand? + meerdere)
3. geo.locate_hotspot      (per brand: echte coördinaten via hoogte +
                           pixelverschuiving + heading)
"""

from . import classify, geo, thermal
from .config import DEFAULT


def detect_event(frame, drone_lat, drone_lon, heading_deg,
                 gps_alt_now, gps_alt_launch, cfg=DEFAULT):
    """Verwerk één meetmoment. Retourneert een plat dict (JSON-klaar).

    - 'fires' bevat alleen geclassificeerde branden, elk verrijkt met
      locatie (hotspot_lat/lon, afstand). Heetste brand eerst.
    - 'hotspots' bevat ALLE blobs (ook afgekeurde) voor diagnose.
    - Locatie wordt alleen voor branden berekend: geen rekenwerk
      verspillen aan ruis (YAGNI).
    """
    ambient, threshold, hotspots = thermal.find_hotspots(frame, cfg)
    agl = geo.agl_from_gps(gps_alt_now, gps_alt_launch)

    fires = classify.classify_all(hotspots, ambient, cfg)
    for brand in fires:
        # Geo-berekening per brand; pixel van de heetste cel bepaalt de
        # kijkrichting (centroid is voor grote branden stabieler, maar de
        # heetste pixel is de interessantste plek voor de operator).
        brand.update(geo.locate_hotspot(
            drone_lat, drone_lon, heading_deg, agl,
            brand["x"], brand["y"], cfg,
        ))

    return {
        "ambient": round(ambient, 1),
        "threshold": round(threshold, 1),
        "agl_m": round(agl, 1),
        "height_warning": geo.check_height(agl, cfg),
        "n_hotspots": len(hotspots),
        "n_fires": len(fires),
        "hotspots": hotspots,
        "fires": fires,
    }
