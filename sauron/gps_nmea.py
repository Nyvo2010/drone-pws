"""NMEA-GPS uitlezen (GEPRC GEP-M10-DQ via flight controller).

De seriële poort is nog onbekend, daarom:
- parse-functies werken op pure strings (testbaar zonder hardware);
- list_candidate_ports() zoekt gebruikelijke USB-serieelpoorten;
- read_lines() leest live, maar importeert pyserial pas bij aanroep
  (geen harde afhankelijkheid: demo en tests draaien zonder).

Ondersteunde zinnen (minimaal, YAGNI):
- $xxGGA: positie + MSL-hoogte + fixkwaliteit/sats/hdop.
- $xxRMC: positie en koers (course over ground) als reserve.
De 'xx' is de talker-ID (GP, GN, GL...); die negeren we bewust.

`parse_nmea_block()` zet een blok ruwe zinnen om naar precies de velden
die het dashboard gebruikt. De ESP32 hoeft de zinnen dan alleen door te
geven (veld `nmea`), zonder zelf een parser te hebben.
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


# NMEA-fixkwaliteit (veld 6 van GGA) -> dashboardschaal.
# 0 = geen fix, 1 = GPS (3D), 2 = DGPS (3D), 4 = RTK, 5 = RTK float.
# Let op: dit is een ándere schaal dan de UBX fixType van de firmware
# (zie esp32.normaliseer_fix); 1 here betekent 2 op het dashboard.
FIX_QUALITY_NAAR_SCHAAL = {0: 0, 1: 2, 2: 2, 3: 0, 4: 3, 5: 3}


def parse_gga(zin):
    """Parse een GGA-zin -> positie, hoogte, fix, sats en hdop (of None).

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
        kwaliteit = int(velden[6]) if velden[6] else 0
        sats = int(velden[7]) if velden[7] else None
        hdop = float(velden[8]) if velden[8] else None
    except (ValueError, IndexError):
        return None
    if lat is None or lon is None or alt is None:
        return None  # geen volledige fix -> onbruikbaar, weggooien
    return {
        "lat": lat, "lon": lon, "alt_msl": alt,
        "fix": FIX_QUALITY_NAAR_SCHAAL.get(kwaliteit, 1),
        "sats": sats, "hdop": hdop,
    }


def parse_rmc(zin):
    """Parse een RMC-zin -> positie en koers (reserve zonder hoogte)."""
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
    resultaat = {"lat": lat, "lon": lon}
    if len(velden) > 8 and velden[8]:
        try:
            resultaat["heading_deg"] = float(velden[8])
        except ValueError:
            pass
    return resultaat


def parse_line(zin):
    """Probeer GGA, dan RMC. Retourneert dict of None."""
    # GGA eerst: die heeft de hoogte die we nodig hebben.
    resultaat = parse_gga(zin)
    if resultaat is not None:
        return resultaat
    return parse_rmc(zin)


def parse_nmea_block(tekst):
    """Blok ruwe NMEA-zinnen -> één dict met dashboardvelden.

    Dit is de route voor de firmware van de teamgenoot: die hoeft de
    zinnen alleen door te geven in het veld `nmea`, de laptop parst ze.
    GGA levert positie, hoogte, fix, sats en hdop; RMC levert de koers
    (alleen zinvol als de drone beweegt). Velden die ontbreken blijven
    weg, zodat de caller alleen aanvult wat hij nog niet had.
    """
    if not isinstance(tekst, str):
        return {}
    uit = {}
    for regel in tekst.split("\n"):
        regel = regel.strip()
        if not regel.startswith("$"):
            continue
        deel = parse_line(regel)
        if not deel:
            continue
        for sleutel, waarde in deel.items():
            if waarde is not None and sleutel not in uit:
                uit[sleutel] = waarde
    return uit


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
