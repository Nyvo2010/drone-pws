"""ESP32-kant: camera-instellingen uitlezen en aanpassen over HTTP.

De firmware op de drone is de Arduino CameraWebServer (Espressif,
libraries/ESP32/examples/Camera/CameraWebServer). Die onthult precies:  :80/status                      JSON met ALLE camera-instellingen plus de
                                  sensor-registers (xclk, framesize,
                                  quality, hmirror, vflip, awb, aec, agc, ...)
  :80/control?var=<naam>&val=<n>  één instelling zetten (cmd_handler in
                                  app_httpd.cpp); ondersteunde namen staan
                                  in CONTROL_VARS hieronder
  :80/capture                     één JPEG (de camera accepteert maar één
                                  client tegelijk -> niet in een lus pollen)
  :81/stream                      MJPEG (draait alleen op builds die de
                                  aparte stream-server starten)

De eigen firmware van de drone (vanaf 21 okt) serveert het warmtebeeld en
de GPS als GET in plaats van te POSTen:

  :80/api/data                    {"frame": [768] of null,
                                  "thermal_available": bool, "gps": {...}}
  :80/api/status                  camera/thermal/gps/wifi-status

Daarom heeft Esp32 naast de CameraWebServer-methoden ook data() en
api_status(), en parse_data() zet /api/data om in een ingest-pakket.

Alles hier is tolerant: een firmware die een endpoint mist levert None,
geen exception. Het dashboard blijft dan gewoon werken.

Namen en waarden komen uit de firmware zelf, dus ze kloppen per definitie:
  - CONTROL_VARS: de var-namen die cmd_handler accepteert
  - FRAMESIZES: de framesize-waarden van de OV5640-pagina
    (index_ov5640.html) -> nummer, label en pixels
"""

import http.client
import json
import socket
import threading
import urllib.parse

from .config import DEFAULT

# Basis-URL van de ESP32 in het drone-net (de ESP32 is het access point).
DEFAULT_BASE_URL = "http://192.168.4.1"


# Sentinel voor een dode pixel uit /api/data (JSON-null). Buiten het
# geldige bereik (-20..600 C), zodat thermal.sanitize_frame hem door de
# mediaan van het frame vervangt in plaats van het frame af te wijzen.
DOOD_PIXEL = -999.0


def stream_url(base_url=DEFAULT_BASE_URL):
    """MJPEG-stream-URL (:81/stream) die bij deze ESP32 hoort."""
    delen = urllib.parse.urlsplit(base_url.rstrip("/"))
    host = delen.hostname or "192.168.4.1"
    return "%s://%s:81/stream" % (delen.scheme or "http", host)

# Alle var-namen die cmd_handler in app_httpd.cpp kent. Onbekende namen
# geven HTTP 500 terug, dus hier niet mee gokken.
CONTROL_VARS = (
    "framesize", "quality", "contrast", "brightness", "saturation",
    "gainceiling", "colorbar", "awb", "agc", "aec", "hmirror", "vflip",
    "awb_gain", "agc_gain", "aec_value", "aec2", "dcw", "bpc", "wpc",
    "raw_gma", "lenc", "special_effect", "wb_mode", "ae_level",
    "led_intensity",
)

# Framesize-waarden van de OV5640 (index_ov5640.html, optie-value -> label).
# De pagina noemt 480x320 "HVGA"; het zijn de pixels die ertoe doen.
FRAMESIZES = {
    0: ("96x96", 96, 96),
    1: ("QQVGA 160x120", 160, 120),
    2: ("128x128", 128, 128),
    3: ("QCIF 176x144", 176, 144),
    4: ("HQVGA 240x176", 240, 176),
    5: ("240x240", 240, 240),
    6: ("QVGA 320x240", 320, 240),
    7: ("320x320", 320, 320),
    8: ("CIF 400x296", 400, 296),
    9: ("HVGA 480x320", 480, 320),
    10: ("VGA 640x480", 640, 480),
    11: ("SVGA 800x600", 800, 600),
    12: ("XGA 1024x768", 1024, 768),
    13: ("HD 1280x720", 1280, 720),
    14: ("SXGA 1280x1024", 1280, 1024),
    15: ("UXGA 1600x1200", 1600, 1200),
    16: ("FHD 1920x1080", 1920, 1080),
    17: ("P HD 720x1280", 720, 1280),
    18: ("P 3MP 864x1564", 864, 1564),
    19: ("QXGA 2048x1564", 2048, 1564),
    20: ("QHD 2560x1440", 2560, 1440),
    21: ("WQXGA 2560x1600", 2560, 1600),
    22: ("P FHD 1080x1920", 1080, 1920),
    23: ("QSXGA 2560x1920", 2560, 1920),
}

# Instellingen die /status teruggeeft naast de sensor-registers.
STATUS_VARS = (
    "xclk", "pixformat", "framesize", "quality", "brightness", "contrast",
    "saturation", "sharpness", "special_effect", "wb_mode", "awb",
    "awb_gain", "aec", "aec2", "ae_level", "aec_value", "agc", "agc_gain",
    "gainceiling", "bpc", "wpc", "raw_gma", "lenc", "hmirror", "vflip",
    "dcw", "colorbar", "led_intensity",
)

# Instellingen die in het dashboard getoond worden, met Nederlandse naam.
UI_VARS = (
    ("framesize", "resolutie"),
    ("quality", "jpeg-kwaliteit"),
    ("hmirror", "spiegel horizontaal"),
    ("vflip", "spiegel verticaal"),
    ("brightness", "helderheid"),
    ("contrast", "contrast"),
    ("saturation", "verzadiging"),
    ("sharpness", "scherpte"),
    ("special_effect", "effect"),
    ("wb_mode", "witte balans"),
    ("awb", "auto witbalans"),
    ("aec", "auto belichting"),
    ("ae_level", "belichtingsniveau"),
    ("agc", "auto versterking"),
    ("gainceiling", "versterkingsplafond"),
    ("lenc", "lenscorrectie"),
    ("bpc", "zwarte punt correctie"),
    ("wpc", "witte punt correctie"),
    ("dcw", "dcw"),
    ("colorbar", "kleurenbalk"),
    ("awb_gain", "awb-versterking"),
    ("agc_gain", "agc-versterking"),
    ("aec_value", "belichtingstijd"),
    ("aec2", "aec2"),
    ("raw_gma", "gma"),
    ("led_intensity", "led"),
)


def framesize_for(width, height):
    """Framesize-waarde voor deze pixels, of None als de sensor ze niet kent."""
    for waarde, (_label, w, h) in FRAMESIZES.items():
        if (w, h) == (width, height):
            return waarde
    return None


def framesize_label(waarde):
    """Mensen-leesbaar label voor een framesize-waarde (of None)."""
    entry = FRAMESIZES.get(waarde)
    return entry[0] if entry else None


def jpeg_size(data):
    """Breedte/hoogte uit een JPEG lezen (SOF0/SOF2-segment).

    Zonder dit zouden we de camera-instelling moeten geloven; de JPEG
    is de waarheid. Geeft (breedte, hoogte) of None als het geen JPEG is.
    """
    if not data or len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        return None
    i = 2
    n = len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xD9:  # EOI
            break
        if i + 4 > n:
            break
        lengte = (data[i + 2] << 8) | data[i + 3]
        # SOF0..SOF15 minus de niet-framesegmenten DHT (C4), JPG (C8), DAC (CC)
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            hoogte = (data[i + 5] << 8) | data[i + 6]
            breedte = (data[i + 7] << 8) | data[i + 8]
            return breedte, hoogte
        i += 2 + max(lengte, 2)
    return None


# De webserver van de ESP32 is single-task: twee requests tegelijk (bv.
# /api/data uit de feed en /api/status uit de monitor) laten hem in de
# praktijk hangen. Daarom één slot per bord: alle clients van deze laptop
# wachten op elkaar in plaats van het bord te overvragen.
_SLOTEN = {}
_SLOT_WACHT = threading.Lock()


def _slot(base_url):
    """Lock voor dit bord (per basis-URL, gedeeld door alle clients)."""
    with _SLOT_WACHT:
        return _SLOTEN.setdefault(base_url.rstrip("/"), threading.Lock())


class Esp32:
    """Kleine HTTP-client voor de camera-server van de ESP32.

    De verbinding blijft open tussen requests (HTTP keep-alive). Vijf keer
    per seconde een nieuwe TCP-handshake doen kost op een ESP32-S3 met
    weinig RAM merkbaar tijd en band; hergebruik halveert de latentie
    zonder dat het bord anders belast wordt. Mislukt een hergebruikte
    verbinding (de firmware sluit hem zelf), dan volgt meteen één nieuwe
    poging op een verse verbinding: geen enkel frame gaat daardoor
    verloren.
    """

    def __init__(self, base_url=DEFAULT_BASE_URL, timeout=3.0,
                 read_timeout=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Verbinden moet snel zijn: duurt dat lang, dan is het bord echt
        # weg. Lezen mag langer duren, want een ESP32 die net een
        # MLX90640-read of een JPEG-encode doet, antwoordt soms pas na een
        # seconde. Met één timeout voor beide gooit een zwakke link frames
        # weg die er wél waren.
        self.read_timeout = timeout if read_timeout is None else read_timeout
        self.slot = _slot(self.base_url)
        self._conn = None

    # -- verbinding --------------------------------------------------------
    def _verbinding(self):
        """Nieuwe (of eerste) TCP-verbinding naar het bord."""
        delen = urllib.parse.urlsplit(self.base_url)
        host = delen.hostname or "192.168.4.1"
        poort = delen.port or (443 if delen.scheme == "https" else 80)
        if delen.scheme == "https":
            conn = http.client.HTTPSConnection(host, poort, timeout=self.timeout)
        else:
            conn = http.client.HTTPConnection(host, poort, timeout=self.timeout)
        conn.connect()
        try:
            conn.sock.settimeout(self.read_timeout)
        except OSError:  # pragma: no cover - defensief
            pass
        return conn

    def close(self):
        """Sluit de bewaarde verbinding (na een fout of bij afsluiten)."""
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pragma: no cover - defensief
                pass

    # -- ruw ---------------------------------------------------------------
    def _open(self, path):
        """GET(path) -> (status, body) of None als de ESP32 niet antwoordt."""
        # Eén bord = één request tegelijk (de webserver is single-task).
        with self.slot:
            for poging in (0, 1):
                vers = self._conn is None
                try:
                    if vers:
                        self._conn = self._verbinding()
                    self._conn.request("GET", path)
                    antwoord = self._conn.getresponse()
                    body = antwoord.read()
                    if antwoord.will_close:
                        # De firmware sluit na dit antwoord: volgende keer
                        # gewoon weer een nieuwe verbinding.
                        self.close()
                    return antwoord.status, body
                except (OSError, ValueError, http.client.HTTPException):
                    # Afgekapt antwoord of dode verbinding. Was dit een
                    # HERGEBRUIKTE verbinding, dan is één nieuwe poging
                    # zinvol (de firmware sluit hem soms zelf). Mislukt een
                    # net opgezette verbinding, dan is het bord echt
                    # onbereikbaar en kost een tweede poging alleen tijd.
                    self.close()
                    if poging or vers:
                        return None
            return None

    def _json(self, path):
        resultaat = self._open(path)
        if resultaat is None:
            return None
        _status, body = resultaat
        if not body:
            return None
        try:
            return json.loads(body.decode("utf-8", errors="replace"))
        except ValueError:
            return None

    # -- camera ------------------------------------------------------------
    def status(self):
        """Alle camera-instellingen van de ESP32 (dict) of None."""
        return self._json("/status")

    def set(self, var, waarde):
        """Eén instelling zetten. True als de firmware het bevestigt (200)."""
        if var not in CONTROL_VARS:
            return False
        query = urllib.parse.urlencode({"var": var, "val": int(waarde)})
        resultaat = self._open("/control?" + query)
        if resultaat is None:
            return False
        status, _body = resultaat
        return status == 200

    def data(self):
        """JSON van /api/data (warmtebeeld) of None."""
        return self._json("/api/data")
    
    def gps(self):
        """JSON van /api/gps (GPS data) of None."""
        return self._json("/api/gps")

    def api_status(self):
        """JSON van /api/status (camera/thermal/gps/wifi) of None."""
        return self._json("/api/status")

    def capture(self):
        """Eén JPEG van de camera (bytes) of None."""
        resultaat = self._open("/capture")
        if resultaat is None:
            return None
        status, body = resultaat
        if status != 200 or not body:
            return None
        return body

    def bereikbaar(self):
        """Is de camera-server echt te bereiken? (echte HTTP-reactie)

        Let op: alleen een TCP-connect is misleidend. Op een laptop met
        VPN kan de tunnel de SYN beantwoorden terwijl er helemaal geen
        drone is; dat gaf een vals "bereikbaar". Daarom vragen we een
        echte HTTP-reactie (/api/status of /status; geen van beide raakt
        de camera aan).
        """
        if self.api_status() is not None:
            return True
        return self._open("/status") is not None


def diagnose(base_url=DEFAULT_BASE_URL, timeout=3.0, use_slot=True):
    """Waarom antwoordt de ESP32 niet? Netwerk of firmware?

    In het veld zie je alleen "niet verbonden", maar er zijn twee heel
    verschillende oorzaken met dezelfde klacht:

    - "antwoordt"   : er komt een HTTP-reactie (ook 404 telt) -> de
                      firmware leeft, alleen dit pad bestaat niet.
    - "hangt"       : de TCP-handshake lukt binnen milliseconden, maar er
                      komt geen enkel byte terug. De WiFi-stack (lwIP)
                      draait dus wél, maar de webtaak van de sketch is
                      geblokkeerd — bijvoorbeeld een MLX90640-read of een
                      I2C-timeout in dezelfde loop. Herstarten helpt tijdelijk;
                      de firmware moet niet blokkeren.
    - "weigert"     : verbinding geweigerd (RST) -> geen webserver, bord
                      nog aan het booten of net geflasht.
    - "onbereikbaar": geen route/ARP -> bord uit of laptop op een ander
                      netwerk.

    Geeft (soort, uitleg) terug; nooit een exception.
    """
    delen = urllib.parse.urlsplit(base_url.rstrip("/"))
    host = delen.hostname or "192.168.4.1"
    poort = delen.port or 80
    if not use_slot:
        # Vanuit de poll-lus: het slot niet pakken, anders wacht het
        # pollen op de diagnose precies op het moment dat herstel telt.
        return _diagnose_onder_slot(host, poort, timeout)
    with _slot(base_url):
        return _diagnose_onder_slot(host, poort, timeout)


def _diagnose_onder_slot(host, poort, timeout):
    try:
        sock = socket.create_connection((host, poort), timeout)
    except socket.timeout:
        return "onbereikbaar", "%s:%d reageert niet (timeout)" % (host, poort)
    except ConnectionRefusedError:
        return "weigert", "%s:%d weigert verbindingen" % (host, poort)
    except OSError as fout:
        return "onbereikbaar", "%s:%d: %s" % (host, poort, fout)
    try:
        sock.settimeout(timeout)
        sock.sendall(("GET /api/status HTTP/1.1\r\nHost: %s\r\n"
                      "Connection: close\r\n\r\n" % host).encode())
        eerste = sock.recv(64)
    except socket.timeout:
        return "hangt", ("%s:%d neemt de verbinding aan maar geeft geen "
                          "antwoord" % (host, poort))
    except OSError as fout:
        return "hangt", "%s:%d: %s" % (host, poort, fout)
    finally:
        try:
            sock.close()
        except OSError:
            pass
    if not eerste:
        return "hangt", ("%s:%d sluit de verbinding zonder antwoord"
                          % (host, poort))
    return "antwoordt", eerste.split(b"\r\n", 1)[0].decode("latin-1",
                                                          "replace")


# De firmware van de drone levert de UBX NAV-PVT fixType. Het dashboard
# rekent met de NMEA-schaal (0 = geen, 1 = 2D, 2 = 3D, 3 = rtk), dus op
# de grens omrekenen: anders zou een 2D-fix (geen bruikbare hoogte) als
# "3D" doorgaan en op een verzonnen AGL coördinaten opleveren.
UBX_FIX_NAAR_SCHAAL = {0: 0, 1: 1, 2: 1, 3: 2, 4: 2, 5: 0}


def normaliseer_fix(waarde):
    """UBX fixType -> dashboardschaal; onbekend blijft ongewijzigd."""
    try:
        nummer = int(float(waarde))
    except (TypeError, ValueError):
        return waarde
    return UBX_FIX_NAAR_SCHAAL.get(nummer, nummer)


def parse_data(data, gps_data=None, verwacht=None):
    """JSON van /api/data -> pakket voor /api/ingest (None = nog geen frame).

    De firmware van de teamgenoot serveert het warmtebeeld via GET:
      {"frame": [768 temperaturen] | null,
       "thermal_available": true|false}

    GPS data wordt apart via /api/gps geleverd:
      {"lat":..,"lon":..,"alt_msl":..,"heading_deg":..,
       "fix":..,"sats":..,"hdop":..} | null

    Wees tolerant: een genest 24x32-frame, een `thermal`-subobject en GPS
    op het hoogste niveau mogen ook; getallen als string worden omgezet.
    Zonder (bruikbaar) frame is er niets te verwerken -> None.
    """
    if isinstance(data, (list, tuple)):
        data = {"frame": data}
    if not isinstance(data, dict):
        return None

    frame = data.get("frame")
    if frame is None:
        frame = (data.get("temps") or data.get("cells")
                 or data.get("temperatures"))
    thermisch = data.get("thermal")
    if frame is None and isinstance(thermisch, dict):
        frame = thermisch.get("frame")
        if frame is None:
            frame = (thermisch.get("temps") or thermisch.get("cells")
                     or thermisch.get("temperatures"))
    if frame is None and isinstance(thermisch, (list, tuple)):
        frame = thermisch  # {"thermal": [768 temperaturen]}
    if frame is None and isinstance(data.get("data"), (list, tuple)):
        frame = data["data"]
    if not isinstance(frame, (list, tuple)) or not frame:
        return None

    rijen = frame if isinstance(frame[0], (list, tuple)) else [frame]
    cellen = []
    try:
        for rij in rijen:
            for waarde in rij:
                # De firmware schrijft dode pixels als JSON-null. Dat is
                # geen kapot frame: thermal.sanitize_frame vervangt elke
                # waarde buiten -20..600 C door de mediaan. Deze sentinel
                # valt daar precies in, terwijl een echte None/NaN het
                # hele frame zou laten afwijzen.
                cellen.append(DOOD_PIXEL if waarde is None
                              else float(waarde))
    except (TypeError, ValueError):
        return None
    # Een afgekapt antwoord kan nog net geldige JSON zijn. Een frame met
    # te weinig waarden is geen meting: terug naar de poll-lus, die hem
    # meteen opnieuw opvraagt (dashboard.esp32_loop).
    if verwacht is None:
        verwacht = DEFAULT.width * DEFAULT.height
    if len(cellen) != verwacht:
        return None
    body = {"frame": cellen}

    # Positie: de firmware zet `drone` in /api/data zodra er een 3D-fix is;
    # /api/gps geeft altijd lat/lon (met nulls) plus fix/sats/hdop. Beide
    # samenvoegen, en een null uit /api/gps mag een echte waarde uit
    # /api/data niet overschrijven.
    drone = {}
    if isinstance(gps_data, dict):
        for sleutel, waarde in gps_data.items():
            if isinstance(waarde, str) and waarde.strip():
                try:
                    waarde = float(waarde)
                except ValueError:
                    pass  # bv. nmea-string: laten staan
            if waarde is None:
                continue
            drone[sleutel] = waarde
    # Het `drone`-blok in /api/data is per frame vers; /api/gps is 1 Hz en
    # kan bij een zwakke link seconden oud zijn. Daarom wint het
    # per-frame-blok, en vult /api/gps alleen aan wat ontbreekt.
    eigen = data.get("drone")
    if isinstance(eigen, dict):
        for sleutel, waarde in eigen.items():
            if waarde is not None:
                drone[sleutel] = waarde
    if drone:
        if "fix" in drone:
            drone["fix"] = normaliseer_fix(drone["fix"])
        body["drone"] = drone

    launch = data.get("gps_alt_launch")
    if launch is not None:
        body["gps_alt_launch"] = launch

    return body


def camera_report(status, gemeten=None):
    """Status-JSON -> rapport voor het dashboard.

    `gemeten` is de (breedte, hoogte) uit een echte JPEG; die wint van
    de framesize-uit de status, want de JPEG is de waarheid.
    """
    if not status:
        return {}
    rapport = {"bereikbaar": True}
    for sleutel in STATUS_VARS:
        if sleutel in status:
            rapport[sleutel] = status[sleutel]
    # Sensor-registers (0x3400 enz.) apart zetten: veel data, weinig nut
    # in de UI, maar wel beschikbaar voor diagnose.
    rapport["registers"] = {
        sleutel: waarde for sleutel, waarde in status.items()
        if sleutel.startswith("0x")
    }
    waarde = rapport.get("framesize")
    label = framesize_label(waarde) if isinstance(waarde, int) else None
    rapport["framesize_label"] = label
    if label:
        rapport["resolutie"] = label.split(" ", 1)[-1]
    if gemeten:
        rapport["resolutie_gemeten"] = "%dx%d" % gemeten
        if label and "%dx%d" % gemeten != rapport.get("resolutie"):
            rapport["resolutie_afwijkend"] = True
    # Sensor-model: OV5640/OV3660 hebben de 0x34xx-registers.
    if "0x3400" in status:
        rapport["sensor"] = "OV5640/OV3660"
    elif "0xd3" in status:
        rapport["sensor"] = "OV2640"
    return rapport


def apply_camera_config(esp, breedte=480, hoogte=320, kwaliteit=10,
                        spiegel=True):
    """Zet de gevraagde camera-instellingen en lees ze terug.

    Werkt via /control van de Arduino CameraWebServer. Het resultaat
    wordt teruggelezen via /status: pas dan weten we zeker dat de
    sensor het ook echt deed (een firmware kan een var negeren).

    Geeft een rapport: wat er gezet is, of het gelezen terug komt en
    wat er misging. Nooit een exception: het veld moet blijven werken.
    """
    rapport = {"gezet": [], "mislukt": [], "notes": []}
    waarde = framesize_for(breedte, hoogte)
    if waarde is None:
        rapport["mislukt"].append(
            "framesize %dx%d kent de sensor niet" % (breedte, hoogte))
    else:
        if esp.set("framesize", waarde):
            rapport["gezet"].append("framesize=%d (%s)" % (waarde, framesize_label(waarde)))
        else:
            rapport["mislukt"].append("framesize=%d" % waarde)
    if kwaliteit is not None:
        if esp.set("quality", int(kwaliteit)):
            rapport["gezet"].append("quality=%d" % kwaliteit)
        else:
            rapport["mislukt"].append("quality=%d" % kwaliteit)
    if spiegel is not None:
        if esp.set("hmirror", 1 if spiegel else 0):
            rapport["gezet"].append("hmirror=%d" % (1 if spiegel else 0))
        else:
            rapport["mislukt"].append("hmirror=%d" % (1 if spiegel else 0))

    status = esp.status()
    if not status:
        rapport["notes"].append("geen /status-antwoord: niet te controleren")
        return rapport
    rapport["status"] = camera_report(status)
    # Terugleescontrole: wat we wilden vs. wat de sensor zegt.
    if waarde is not None and status.get("framesize") != waarde:
        rapport["mislukt"].append(
            "framesize bleef %s (wilden %d)" % (status.get("framesize"), waarde))
    if kwaliteit is not None and status.get("quality") != int(kwaliteit):
        rapport["mislukt"].append(
            "quality bleef %s (wilde %d)" % (status.get("quality"), kwaliteit))
    if spiegel is not None and status.get("hmirror") != (1 if spiegel else 0):
        rapport["mislukt"].append(
            "hmirror bleef %s (wilde %d)"
            % (status.get("hmirror"), 1 if spiegel else 0))
    return rapport
