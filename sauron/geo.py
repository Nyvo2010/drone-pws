"""Locatie-berekening: van hotspot-pixel naar echte GPS-coördinaten.

Situatie (vastgelegd met het team):
- Warmtecamera kijkt RECHT NAAR BENEDEN. Er is dus geen pitch-rotatie
  nodig: elke pixel kijkt onder een vaste hoek schuin omlaag.
- GPS meet hoogte t.o.v. zeeniveau (MSL). De brand ligt (aanname) op
  dezelfde hoogte als het lanceerpunt, dus:
      hoogte_boven_grond = gps_hoogte_nu - gps_hoogte_lancering.
  Geen geoid-wiskunde nodig: beide metingen delen hetzelfde datum, het
  verschil valt precies weg.
- Bijna geen wind: we compenseren niet voor drift (YAGNI).

Goniometrie per hotspot-pixel, in drie stappen:
1. pixel -> kijkhoeken (alpha = rechts, beta = vooruit) via FOV.
2. hoeken + hoogte -> grondverschuiving in meters (tangens: overstaande
   = aanliggende * tan(hoek), met de vlieghoogte als aanliggende zijde).
3. meters -> kompas (rotatie met heading via sinus/cosinus) -> lat/lon.

Speciaal geval: pixel in het beeldcentrum -> hoeken ~0 -> verschuiving
~0 -> hotspot ≈ dronepositie. Dat is exact het "recht erboven vliegen"
idee van het team, maar dan als limietgeval van dezelfde formule.
"""

import math

from .config import DEFAULT, Config


def agl_from_gps(alt_now_msl, alt_launch_msl):
    """Hoogte boven het lanceerpunt (AGL) uit twee GPS-hoogtes.

    Beide zijn MSL-hoogtes; het verschil is de hoogte boven de grond
    zolang de brand op lanceerpunthoogte ligt (team-aanname).
    """
    return float(alt_now_msl) - float(alt_launch_msl)


def check_height(agl, cfg=DEFAULT):
    """Waarschuwing als de hoogte buiten het 5-30 m testbereik valt.

    Retourneert None als alles normaal is, anders een tekst voor de
    operator. Geen harde fout: liever een verdachte meting mét melding
    dan een crash in het veld.
    """
    if agl < cfg.agl_min_m:
        return "lager dan %.0f m: grondvlek klein, kans op vals alarm" % cfg.agl_min_m
    if agl > cfg.agl_max_m:
        return "hoger dan %.0f m: pixels groot, kleine brand onzichtbaar" % cfg.agl_max_m
    return None


def pixel_to_angles(x, y, cfg=DEFAULT):
    """Pixel -> kijkhoeken in graden: (alpha_rechts, beta_vooruit).

    Het beeldcentrum is het nulpunt: het centrum van 32 pixels ligt
    tussen kolom 15 en 16 (cx = 15,5). Elke pixelbreedte is FOV / aantal
    pixels. Positief alpha = rechts van het midden, positief beta = voor
    de drone (neus) — mits row0_is_forward klopt met de montage!
    """
    cx = (cfg.width - 1) / 2.0
    cy = (cfg.height - 1) / 2.0
    alpha = (x - cx) / cfg.width * cfg.fov_h_deg
    if cfg.row0_is_forward:
        beta = (cy - y) / cfg.height * cfg.fov_v_deg  # rij 0 = vooruit
    else:
        beta = (y - cy) / cfg.height * cfg.fov_v_deg  # sensor omgedraaid
    return alpha, beta


def ground_offset_m(alpha_deg, beta_deg, agl):
    """Hoeken + hoogte -> verschuiving over de grond in meters.

    Rechte driehoek per as: de drone hangt 'agl' meter boven de grond
    (aanliggende zijde), de kijkstraal wijkt 'hoek' af van verticaal,
    dus de grondafstand (overstaande zijde) = agl * tan(hoek).
    Retourneert (rechts_m, vooruit_m).
    """
    rechts = agl * math.tan(math.radians(alpha_deg))
    vooruit = agl * math.tan(math.radians(beta_deg))
    return rechts, vooruit


def rotate_to_compass(vooruit_m, rechts_m, heading_deg):
    """Draai (vooruit, rechts) naar (oost, noord) met de kompasheading.

    Heading = graden rechtsom vanaf het noorden. De neus-vector is dan
    (sin h, cos h) in (oost, noord) en de rechtervleugel-vector is
    (cos h, -sin h). Check: heading 90 (oost) -> neus = (1, 0). Klopt.
    """
    h = math.radians(heading_deg)
    oost = vooruit_m * math.sin(h) + rechts_m * math.cos(h)
    noord = vooruit_m * math.cos(h) - rechts_m * math.sin(h)
    return oost, noord


def offset_to_latlon(lat, lon, oost_m, noord_m, cfg=DEFAULT):
    """Verschuiving in meters -> nieuwe GPS-coördinaten.

    Platte-aarde benadering: 1 graad breedte is altijd ~111,32 km;
    1 graad lengte krimpt met cos(breedte). Voor onze afstanden
    (< 100 m) is de fout verwaarloosbaar (< centimeters).
    """
    dlat = noord_m / cfg.meters_per_deg_lat
    dlon = oost_m / (cfg.meters_per_deg_lat * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def footprint_m(agl, cfg=DEFAULT):
    """Hoe groot is het camerabeeld op de grond? (breedte, hoogte, px-maten).

    Handig voor de operator: bij 15 m hoogte dekt het beeld ca. 43 x 23 m,
    dus 1 pixel is dan ~1,3 x 1,0 m. Een brand kleiner dan een pixel
    wordt uitgemiddeld en lijkt kouder dan hij is!
    """
    breedte = 2.0 * agl * math.tan(math.radians(cfg.fov_h_deg / 2.0))
    hoogte = 2.0 * agl * math.tan(math.radians(cfg.fov_v_deg / 2.0))
    return {
        "breedte_m": breedte,
        "hoogte_m": hoogte,
        "pixel_breedte_m": breedte / cfg.width,
        "pixel_hoogte_m": hoogte / cfg.height,
    }


def locate_hotspot(drone_lat, drone_lon, heading_deg, agl, x, y, cfg=DEFAULT):
    """Volledige keten: dronepositie + pixel -> hotspot-positie.

    Retourneert dict met tussenstappen (hoeken, meters, kompas) zodat de
    berekening in het veld controleerbaar blijft, plus de uiteindelijke
    hotspot_lat/hotspot_lon en de afstand drone -> hotspot.
    """
    if agl <= 0:
        raise ValueError("AGL moet positief zijn, kreeg %r" % (agl,))
    alpha, beta = pixel_to_angles(x, y, cfg)
    rechts_m, vooruit_m = ground_offset_m(alpha, beta, agl)
    oost_m, noord_m = rotate_to_compass(vooruit_m, rechts_m, heading_deg)
    lat, lon = offset_to_latlon(drone_lat, drone_lon, oost_m, noord_m, cfg)
    return {
        "alpha_rechts_deg": round(alpha, 2),
        "beta_vooruit_deg": round(beta, 2),
        "rechts_m": round(rechts_m, 2),
        "vooruit_m": round(vooruit_m, 2),
        "oost_m": round(oost_m, 2),
        "noord_m": round(noord_m, 2),
        "afstand_m": round(math.hypot(oost_m, noord_m), 2),
        "hotspot_lat": lat,
        "hotspot_lon": lon,
    }
