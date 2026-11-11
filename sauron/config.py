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

Waarom deze drempels (dit is de kern van "geen brand op een steen"):

- De MLX90640 meet een schijnbare temperatuur per pixel. Op 15 m AGL is
  een pixel ongeveer 1,3 x 1,0 m grond. Een bosbrand van 1 m2 vult zo'n
  pixel bijna helemaal en leest dan honderden graden.
- Zonverwarmde stenen, asfalt en daken halen in de praktijk 55-70 C,
  ook als de lucht maar 25 C is. Een regel als "omgeving + 10 C" maakt
  daar dus een brand van. Daarom telt absolute hitte (>= 90 C) EN een
  grote sprong boven de omgeving (>= 45 C). Wat daar tussenin zit
  (60-90 C) is een "verdacht" warm voorwerp, geen brand.
- De sensor is gespecificeerd tot 300 C. Metingen boven 350 C zijn
  leesfouten (dode pixel, I2C-flard) en worden door de mediaan vervangen.
- Een frame waarvan de mediaan buiten -15..70 C ligt, is geen beeld van
  de grond: de sensor is dan niet op temperatuur (net aangezet) of het
  frame is kapot. Zo'n frame geeft een waarschuwing en geen branden.
- Eén frame is nog geen brand: dezelfde plek moet in twee opeenvolgende
  frames heet zijn voordat de melding "bevestigd" is. Losse flarden
  verdwijnen daardoor uit het waarschuwingsbeeld.
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

    # -- Validatie van meetwaarden --------------------------------------
    # Dode pixels en I2C-flarden van de MLX90640 geven waarden als -273 of
    # 1000+ C, en een beschadigde read kan ook 400-600 C geven. Buiten dit
    # bereik is het geen temperatuur maar een sensorfout: zo'n cel wordt
    # door de mediaan van het frame vervangen voordat we blobs zoeken.
    # 350 C = bovengrens van de sensor (300 C) plus marge.
    valid_temp_min_c: float = -20.0
    valid_temp_max_c: float = 350.0

    # -- Plausibiliteit van het hele frame ------------------------------
    # Mediaan buiten deze band = geen geloofwaardig beeld van de grond.
    # (Log 30 okt: mediaan 486 C en 137 "branden" uit één vlucht.)
    ambient_min_c: float = -15.0
    ambient_max_c: float = 70.0
    # Meer dan dit deel van de pixels op de sensorgrens = verzadigd beeld
    # (sensor kijkt in de zon, of de read is mislukt).
    max_saturated_fraction: float = 0.15

    # -- Laag 1: heat point identificatie ------------------------------
    # Drempel = omgevingstemperatuur + deze marge. Bepaalt welke pixels
    # überhaupt als "warm punt" meetellen; de classificatie hieronder
    # beslist of het ook een brand is.
    threshold_above_ambient: float = 12.0
    # Kleinste blob die we serieus nemen, in pixels. Eén pixel is ruis
    # (dode pixel, reflectie); 3 aaneengesloten pixels is een echt voorwerp.
    min_area_pixels: int = 3

    # -- Laag 2: classificatie (twee standen) --------------------------
    # "verdacht": heter dan alles wat de zon op de grond kan maken.
    # Operatorkant: interessant om te bekijken, geen brandmelding.
    suspect_min_abs_c: float = 60.0
    suspect_min_delta_c: float = 30.0
    # "brand": absolute hitte EN een sprong die alleen een vuur maakt.
    fire_min_abs_c: float = 90.0
    fire_min_delta_c: float = 45.0

    # -- Tijdsconsistentie ---------------------------------------------
    # Aantal metingen (frames) voordat een brand "bevestigd" is. Met 4 Hz
    # means dit een halve seconde: snel genoeg voor het veld, langzaam
    # genoeg om een losse sensorflard geen melding te laten worden.
    confirm_observations: int = 2

    # -- Brand-tracking over frames -------------------------------------
    # Zelfde brand binnen deze straal (wereldcoördinaten) = zelfde track.
    track_match_radius_m: float = 8.0
    # Zonder geldige locatie (AGL <= 0) matchen we op pixelafstand.
    track_pixel_radius: int = 4
    # Na deze stilte (seconden) is een brand "uit beeld".
    track_lost_after_s: float = 2.5
    # Uit-beeld-tracks blijven zo lang beschikbaar voor herdetectie.
    track_archive_after_s: float = 120.0

    # -- Geometrie: hoogte ----------------------------------------------
    # Verwacht vliegbereik boven het lanceerpunt. Buiten deze band geven
    # we een waarschuwing (geen harde fout: liever een melding dan crash).
    agl_min_m: float = 5.0
    agl_max_m: float = 30.0

    # Omrekening meters -> graden (platte-aarde benadering, geldig voor
    # afstanden < enkele honderden meters, dus ruim genoeg hier).
    meters_per_deg_lat: float = 111320.0

    # -- Camera en link --------------------------------------------------
    # 480x320 met kwaliteit 10: klein genoeg om naast de MJPEG-stream
    # soepel te blijven, groot genoeg om rook te herkennen. Alleen van
    # toepassing op de stock CameraWebServer (/status + /control); de
    # eigen firmware van de drone heeft die endpoints niet.
    camera_width: int = 480
    camera_height: int = 320
    camera_quality: int = 10
    # Poll-cadans van /api/data. De sensor ververst op 8 Hz; 4 Hz is
    # vloeiend en laat genoeg band over voor de RGB-stream.
    poll_interval_s: float = 0.25
    # Een positie ouder dan dit levert geen brandcoördinaten meer op.
    # /api/gps komt op 1 Hz; valt die weg (zwakke link) dan komt het
    # warmtebeeld vaak wél door. Rekenen met een oude positie geeft
    # coördinaten die niet meer kloppen, dus na 3 s zeggen we "positie te
    # oud" in plaats van te gokken.
    max_position_age_s: float = 3.0


# Eén gedeelde standaardconfiguratie voor het hele programma.
DEFAULT = Config()
