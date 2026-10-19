"""Centrale instellingen voor Sauron.

Alles wat tijdens veldtesten nog gekalibreerd moet worden staat hier,
zodat er nooit "magische getallen" verspreid in de code staan.

Vastgelegde hardware-aannames (van het team):
- Warmtecamera (MLX90640) kijkt RECHT NAAR BENEDEN (pitch vast -90 graden).
- RGB-camera kijkt VOORUIT (horizontaal) en doet dus NIET mee in de
  geometrie-berekening: er is geen RGB-thermal overlay mogelijk omdat de
  kijkrichtingen verschillen.
- MLX90640 wide-variant: FOV 110 graden horizontaal, 75 verticaal.
  ("110" uit de teamafstemming; aanpasbaar als ander type blijkt.)
- GPS levert NMEA-zinnen; seriële poort is nog onbekend -> zie gps_nmea.
- Vlieghoogte boven lanceerpunt: 5 tot 30 meter, bijna geen wind.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Alle drempels en hardware-parameters op één plek."""

    # -- MLX90640 sensorgeometrie -------------------------------------
    width: int = 32          # pixels horizontaal (vast voor MLX90640)
    height: int = 24         # pixels verticaal (vast voor MLX90640)
    fov_h_deg: float = 110.0  # horizontale openingshoek (wide-variant)
    fov_v_deg: float = 75.0   # verticale openingshoek (wide-variant)
    # Rij 0 van het frame = voorkant (neus) van de drone. Als de sensor
    # 180 graden gedraaid is gemonteerd, zet dit op False.
    row0_is_forward: bool = True

    # -- Laag 1: heat point identificatie ------------------------------
    # Drempel = omgevingstemperatuur + deze marge. Hoger = minder vals
    # alarm (zon/warme daken), lager = vroegere detectie. Kalibreren!
    threshold_above_ambient: float = 12.0
    # Kleinste blob die we serieus nemen, in pixels. Bij 10 m hoogte is
    # 1 pixel ca. 0,9 m breed, dus 3 pixels is grofweg een beginnend
    # brandje van enkele m2. Kleiner = ruis (dode pixels, reflecties).
    min_area_pixels: int = 3

    # -- Laag 2: classificatie -----------------------------------------
    # Minimale temperatuurstijging boven omgeving voor "mogelijke brand".
    fire_min_delta: float = 10.0
    # Absolute ondergrens: kouder dan dit is nooit een bosbrand,
    # ook niet bij een koude dag (voorkomt winter-vals-alarm).
    fire_min_abs: float = 40.0

    # -- Geometrie: hoogte ----------------------------------------------
    # Verwacht vliegbereik boven het lanceerpunt. Buiten deze band geven
    # we een waarschuwing (geen harde fout: liever een melding dan crash).
    agl_min_m: float = 5.0
    agl_max_m: float = 30.0

    # Omrekening meters -> graden (platte-aarde benadering, geldig voor
    # afstanden < enkele honderden meters, dus ruim genoeg hier).
    meters_per_deg_lat: float = 111320.0


# Eén gedeelde standaardconfiguratie voor het hele programma.
DEFAULT = Config()
