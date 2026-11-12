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
  daar dus een brand van. Daarom is de SPRONG boven de omgeving de
  hoofdregel (>= 60 C): die is onafhankelijk van de luchttemperatuur, van
  de hoogte en van hoeveel van de pixel gevuld is. Een vaste absolute
  grens (zoals 90 C) werkt niet: een echte brand las op 1 m 49-116 C, en
  op hoogte vult een vlam soms maar één pixel van 100 C. Absolute hitte
  (>= 90 C) blijft als tweede weg staan voor een vlam die de pixel vult.
  Wat tussen 30 en 60 C boven de omgeving zit is "verdacht", geen brand.
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
    # Horizontaal spiegelen van het warmtebeeld. De firmware levert het frame
    # al gespiegeld aan (SAURON_MIRROR_X 1 in sauron_poster.h); deze vlag zet
    # het beeld in de stand waarin de operator meekijkt. De flip gebeurt één
    # keer, op de server, vóór detectie én weergave: anders zou de hotspot
    # links in beeld staan terwijl de coördinaten rechts uitrekenen.
    mirror_frame_x: bool = True

    # -- Validatie van meetwaarden --------------------------------------
    # Dode pixels en I2C-flarden van de MLX90640 geven waarden als -273 of
    # 1000+ C, en een beschadigde read kan ook 400-600 C geven. Buiten dit
    # bereik is het geen temperatuur maar een sensorfout: zo'n cel wordt
    # door de mediaan van het frame vervangen voordat we blobs zoeken.
    # 350 C = bovengrens van de sensor (300 C) plus marge.
    valid_temp_min_c: float = -20.0
    valid_temp_max_c: float = 350.0
    # Een echt vuur dichtbij is heter dan de sensor kan uitdrukken (log 11 nov
    # 14:07: één frame met 640 C in de rauwe waarden). Zo'n gebied is geen
    # kapotte pixel: alleen een aaneengesloten groep van minstens dit aantal
    # cellen boven de grens wordt als heet voorwerp behandeld en op
    # valid_temp_max_c geklemd. Kleinere clusters (de 3-pixel flarden van
    # 30 okt, 565 C) blijven sensorruis en worden door de mediaan vervangen.
    min_saturated_pixels: int = 6

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
    # ... maar grootte is niet de enige regel: een bron die gloeiend heet is,
    # telt altijd mee. Op 30 m AGL is één pixel ~2,6 x 1,9 m, dus een vlam
    # die kleiner is dan dat levert één pixel van honderden graden. Zo'n cel
    # is geen ruis (dode pixels halen de mediaan niet, zonverwarmde stenen
    # blijven onder 70 C, een spiegelreflectie haalt geen 200 C).
    small_blob_max_c: float = 200.0
    # ... en de relatieve variant daarvan: één pixel die ver boven de
    # omgeving uitkomt is ook een vlam. Op hoogte vult een vlam minder dan
    # een cel en leest hij bijvoorbeeld 115 C bij een veld van 12 C; 200 C
    # als enige uitzondering zou die vlam als ruis wegzetten.
    small_blob_delta_c: float = 60.0
    # Kleine gaten tussen hete cellen (rook, één cel net onder de drempel)
    # horen bij dezelfde vlam. Zonder samenvoegen werd één vlam op hoogte
    # drie losse 1-pixel-tracks (15:35: 328/185/79 C op (4,7), (8,7),
    # (6,7)) die elk na één frame verdwenen en dus nooit bevestigd werden.
    # Radius in cellen; overbrugt gaten tot 2x deze radius.
    blob_merge_radius: int = 1

    # -- Lokale vergelijking: de hoogte-onafhankelijke kern --------------
    # De mediaan van het HELE frame is een grove omgeving: op 15 m AGL is
    # de vlam één of twee cellen, terwijl de mediaan door koude grond en
    # schaduw wordt bepaald. Daarom vergelijkt elke blob ook met een ring
    # cellen direct om zich heen: "hoeveel heter is dit dan de dingen
    # eromheen". Dat is de maat die blijft kloppen als de vlam maar een
    # halve cel vult, want de grond naast de vlam blijft koud.
    local_ring_px: int = 4
    # Vlam dichtbij zijn eigen omgeving. Passieve oppervlakken halen in de
    # zon 17-39 C boven de lucht (steen 30 okt, dakpan 11 nov); +45 C
    # lokaal is met geen steen, dakpan of asfalt te maken.
    fire_local_delta_c: float = 45.0
    # ... maar de bron moet ook zelf warm zijn: een schaduwrand van 10 C
    # boven een veld van 2 C is geen brand. Veldlucht 11 nov was 7-10 C,
    # dus dit filtert alleen koude ruis, geen echte vlam.
    fire_local_abs_c: float = 50.0
    # Een vlam heeft een hete kern: de heetste cel steekt duidelijk boven
    # het gemiddelde van de blob uit. Een zonverwarmde steen is vlak van
    # temperatuur (contrast ~0-3 C). Alleen geëist vanaf 3 cellen; bij 1-2
    # cellen is er geen structuur te meten en telt de lokale sprong alleen.
    fire_core_contrast_c: float = 6.0

    # -- Laag 2: classificatie (relatief, niet absoluut) ----------------
    # Hoofdregel: de sprong boven de omgeving. Een brand is niet "boven een
    # vaste temperatuur", maar heter dan de grond eromheen. Die sprong is
    # het enige signaal dat blijft kloppen als de drone hoog vliegt (de
    # vlam vult dan minder dan een pixel en leest lager) en als de lucht
    # zelf warm is. Passieve oppervlakken (steen, asfalt, dakpan) halen in
    # de zon 40-50 C boven de lucht; 60 C boven de mediaan is alleen met
    # een vuur te maken. Velddata 11 nov: een echte brand op 1 m gaf 44-105
    # C sprong, een steen 17 C en een warme dakpan 39 C.
    fire_delta_c: float = 60.0
    # "verdacht": interessant om te bekijken, geen brandmelding.
    suspect_delta_c: float = 30.0
    # Tweede weg naar "brand": dichtbij en vol in beeld is de absolute
    # waarde zelf hoog. Nodig voor een vuur in een al heet veld (lucht 40 C,
    # vlam 100 C: sprong 60 C zit precies op de rand).
    fire_min_abs_c: float = 90.0
    fire_min_abs_delta_c: float = 45.0

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
    # GPS-hoogte ruist enkele meters. Mediaan over dit aantal samples (4 Hz
    # -> ca. 0,5 s) dempt een losse uitschieter; de laagste mediaan die we
    # zien is de grond. Kort houden: bij een klim mag AGL niet achterlopen
    # (25 -> 35 m moet meteen 10 m zijn). Zonder dit werd AGL in de vlucht
    # van 15:26 0 tot -6 m en verloor ELKE brand zijn coördinaten.
    alt_window_samples: int = 3

    # -- Kompas / cameramontage ------------------------------------------
    # Offset tussen de kompasheading en de montage van de warmtecamera:
    # 0 = aanname "rij 0 = neus". Staat de sensor gedraaid gemonteerd, zet
    # hier het verschil. Zonder deze knop draaien alle coördinaten mee de
    # verkeerde kant op en is dat niet te corrigeren zonder code.
    heading_offset_deg: float = 0.0

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
    # Poll-cadans van /api/data. De sensor leest op 16 Hz; 4 Hz is vloeiend
    # en laat genoeg band over voor de RGB-stream.
    poll_interval_s: float = 0.25
    # Een positie ouder dan dit levert geen brandcoördinaten meer op.
    # /api/gps komt op 1 Hz; valt die weg (zwakke link) dan komt het
    # warmtebeeld vaak wél door. Rekenen met een oude positie geeft
    # coördinaten die niet meer kloppen, dus na 3 s zeggen we "positie te
    # oud" in plaats van te gokken.
    max_position_age_s: float = 3.0


# Eén gedeelde standaardconfiguratie voor het hele programma.
DEFAULT = Config()


def groot_genoeg(area, max_temp, cfg=DEFAULT, ambient=None):
    """Is deze blob een echt voorwerp en geen sensorruis?

    Drie aaneengesloten pixels is de normale ondergrens. Daarnaast telt een
    bron die ver boven de omgeving uitkomt altijd mee, ook als het maar één
    pixel is: op hoogte vult een vlam soms minder dan een cel en leest hij
    bijvoorbeeld 115 C in een veld van 12 C. Die relatieve uitzondering is
    beter dan een vaste 200 C, want een kleine vlam op hoogte haalt die
    200 C niet en zou dan als ruis verdwijnen.
    """
    if area >= cfg.min_area_pixels:
        return True
    if max_temp >= cfg.small_blob_max_c:
        return True
    if ambient is None:
        return False
    return (max_temp - ambient) >= cfg.small_blob_delta_c
