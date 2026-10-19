"""NMEA-GPS uitlezen (GEPRC GEP-M10-DQ via flight controller).

De seriële poort is nog onbekend, daarom:
- parse-functies werken op pure strings (testbaar zonder hardware);
- list_candidate_ports() zoekt gebruikelijke USB-serieelpoorten;
- read_lines() leest live, maar importeert pyserial pas bij aanroep
  (geen harde afhankelijkheid: demo en tests draaien zonder).

Ondersteunde zinnen (minimaal, YAGNI):
- $xxGGA: positie + MSL-hoogte (alles wat geo.py nodig heeft).
- $xxRMC: positie als reserve (geen hoogte).
De 'xx' is de talker-ID (GP, GN, GL...); die negeren we bewust.
"""

import glob


def nmea_to_decimal(waarde, hemisfeer):
    """Zet NMEA-coördinaat (DDMM.MMMM / DDDMM.MMMM) om naar decimale graden.

    Breedte heeft 2 graden-cijfers (N/S), lengte 3 (E/W). Z/Z/W zijn
    negatief. Lege waarde -> None (geen fix) in plaats van crashen.
    """
    if not waarde or not hemisfeer:
        return None
    cijfers_voor_minuten = 2 if hemisfeer in ("N", "S") else 3
    graden = int(waarde[:cijfers_voor_minuten])
    minuten = float(waarde[cijfers_voor_minuten:])
    decimaal = graden + minuten / 60.0
    if hemisfeer in ("S", "W"):
        decimaal = -decimaal
    return decimaal


def parse_gga(zin):
    """Parse een GGA-zin -> {lat, lon, alt_msl} of None.

    Veldvolgorde: $xxGGA,tijd,lat,N/S,lon,E/W,fix,...,hoogte,M,...
    alt_msl is de GPS-hoogte t.o.v. zeeniveau — precies wat agl_from_gps
    nodig heeft (lancering aftrekken, klaar).
    """
    velden = zin.strip().split(",")
    if len(velden) < 10 or not velden[0].endswith("GGA"):
        return None
    try:
        lat = nmea_to_decimal(velden[2], velden[3])
        lon = nmea_to_decimal(velden[4], velden[5])
        alt = float(velden[9]) if velden[9] else None
    except (ValueError, IndexError):
        return None
    if lat is None or lon is None or alt is None:
        return None  # geen volledige fix -> onbruikbaar, weggooien
    return {"lat": lat, "lon": lon, "alt_msl": alt}


def parse_rmc(zin):
    """Parse een RMC-zin -> {lat, lon} of None (reserve zonder hoogte)."""
    velden = zin.strip().split(",")
    if len(velden) < 7 or not velden[0].endswith("RMC"):
        return None
    if velden[2] != "A":
        return None  # status V = void (geen fix)
    try:
        lat = nmea_to_decimal(velden[3], velden[4])
        lon = nmea_to_decimal(velden[5], velden[6])
    except (ValueError, IndexError):
        return None
    if lat is None or lon is None:
        return None
    return {"lat": lat, "lon": lon}


def parse_line(zin):
    """Probeer GGA, dan RMC. Retourneert dict of None."""
    # GGA eerst: die heeft de hoogte die we nodig hebben.
    resultaat = parse_gga(zin)
    if resultaat is not None:
        return resultaat
    return parse_rmc(zin)


def list_candidate_ports():
    """Zoek waarschijnlijke USB-serieelpoorten (macOS/Linux/Windows).

    De GPS hangt via USB aan de laptop zodra de flight controller is
    aangesloten. Staat de poort er niet bij, geef hem handmatig mee aan
    read_lines() — deze lijst is een hulpmiddel, geen garantie.
    """
    patronen = (
        "/dev/ttyUSB*",  # Linux USB-serieel
        "/dev/ttyACM*",  # Linux USB-modem (veel FC's)
        "/dev/tty.usb*",  # macOS USB-serieel
        "/dev/cu.usb*",  # macOS callout-variant
        "COM*",  # Windows (glob werkt hier beperkt)
    )
    gevonden = []
    for patroon in patronen:
        gevonden.extend(glob.glob(patroon))
    return sorted(set(gevonden))


def read_lines(port, baud=9600):
    """Live NMEA-regels lezen van een seriële poort (generator).

    pyserial wordt pas hier geïmporteerd, zodat de rest van Sauron ook
    zonder werkt. Gebruik: parse_line(regel) per opbrengst.
    Veldtip: de FC praat meestal 115200 baud; werkt 9600 niet, probeer dat.
    """
    import serial  # noqa: WPS433 (bewust late import, zie docstring)

    with serial.Serial(port, baud, timeout=1) as verbinding:
        while True:
            regel = verbinding.readline().decode("ascii", errors="ignore")
            if regel:
                yield regel.strip()
