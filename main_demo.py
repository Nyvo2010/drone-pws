"""Demo: draai de volledige keten op gesimuleerde data.

Geen hardware nodig. Twee scenario's:
1. Brand: gaussische warme vlek (85 C kern) op een veld van 22 C.
2. Geen brand: alleen omgevingswarmte + kleine schommeling.

Starten:  python3 main_demo.py
"""

from sauron import geo, gps_nmea, pipeline
from sauron.config import DEFAULT
from sauron.sim import make_frame


def toon_heatmap(frame):
    """Simpele ASCII-heatmap (24x32) voor in de terminal.

    Vervangt matplotlib (YAGNI): goed genoeg om te zien WAAR het heet is.
    """
    tekens = " .:-=+*#%@"
    minimum = min(frame)
    maximum = max(frame)
    spreiding = max(maximum - minimum, 0.001)  # nooit delen door nul
    print("  heatmap (koud links, heet rechts: '%s'), max=%.1f C"
          % (tekens, maximum))
    for rij in range(DEFAULT.height):
        regel = ""
        for kolom in range(DEFAULT.width):
            norm = (frame[rij * DEFAULT.width + kolom] - minimum) / spreiding
            regel += tekens[min(int(norm * len(tekens)), len(tekens) - 1)]
        print("  " + regel)


def toon_resultaat(label, resultaat):
    """Druk een detectieresultaat leesbaar af."""
    print("\n== %s ==" % label)
    print("  omgeving: %.1f C, drempel: %.1f C, AGL: %.1f m"
          % (resultaat["ambient"], resultaat["threshold"], resultaat["agl_m"]))
    if resultaat["height_warning"]:
        print("  LET OP: %s" % resultaat["height_warning"])
    print("  hotspots: %d, branden: %d"
          % (resultaat["n_hotspots"], resultaat["n_fires"]))
    for i, brand in enumerate(resultaat["fires"], 1):
        print("  brand %d: %.1f C (stijging %.1f C), %d px, score %.2f"
              % (i, brand["max_temp"], brand["delta_t"],
                 brand["area"], brand["score"]))
        print("    pixel (%d, %d), %.1f m %s van drone"
              % (brand["x"], brand["y"], brand["afstand_m"],
                 "weg" if brand["afstand_m"] > 0.5 else "(recht eronder!)"))
        print("    hotspot: %.6f, %.6f" % (brand["hotspot_lat"], brand["hotspot_lon"]))


def main():
    # Vaste demo-positie: drone op 25 m MSL, gelanceerd vanaf 10 m MSL
    # -> AGL = 15 m (midden in het 5-30 m testbereik), heading 90 (oost).
    drone = dict(lat=52.090000, lon=4.310000, heading=90.0,
                 alt_nu=25.0, alt_lancering=10.0)

    # Scenario 1: één brand rechts-voor in beeld.
    frame_brand = make_frame(vlekken=[(20, 8, 85.0, 2.5)])
    toon_heatmap(frame_brand)
    resultaat = pipeline.detect_event(frame_brand, drone["lat"], drone["lon"],
                                      drone["heading"], drone["alt_nu"],
                                      drone["alt_lancering"])
    toon_resultaat("scenario 1: brand aanwezig", resultaat)

    # Scenario 2: geen brand (alleen warme dag + ruis).
    frame_leeg = make_frame(ambient=28.0, vlekken=[])
    resultaat2 = pipeline.detect_event(frame_leeg, drone["lat"], drone["lon"],
                                       drone["heading"], drone["alt_nu"],
                                       drone["alt_lancering"])
    toon_resultaat("scenario 2: geen brand", resultaat2)

    # NMEA-voorbeeld: zo komt de GPS-hoogte straks binnen via de FC.
    zin = "$GPGGA,123519,5205.4000,N,00418.6000,E,1,08,0.9,25.0,M,0.0,M,,*47"
    print("\nNMEA-voorbeeld: %s" % zin)
    print("  parsed: %s" % gps_nmea.parse_line(zin))
    print("  AGL-check: 25.0 - 10.0 = %.1f m" % geo.agl_from_gps(25.0, 10.0))
    print("  poortkandidaten op deze laptop: %s"
          % (gps_nmea.list_candidate_ports() or "geen gevonden"))


if __name__ == "__main__":
    main()
