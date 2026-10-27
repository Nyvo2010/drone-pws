"""UDP-ontdekking: de ESP32 vindt de dashboard zonder hardgecodeerd IP.

Het IP van de laptop verandert (thuisnet, drone-AP, ander netwerk), terwijl
de firmware niet elke vlucht opnieuw geflasht kan worden. Daarom:

  ESP32  --UDP broadcast "SAURON?"-->  poort 8001 (laptop)
  ESP32  <--UDP unicast de ingest-URL--  laptop

De ESP32 stuurt de broadcast tot hij een antwoord heeft en onthoudt de URL
voor die sessie. Zo werkt het altijd, op elk netwerk, zonder configuratie.

Alleen de stdlib, één thread, geen camera- of netwerkverkeer buiten deze
twee pakketjes.
"""

import socket
import threading

POORT = 8001           # UDP-poort waarop de dashboard luistert
VERBINDER = b"SAURON"  # wat de ESP32 stuurt (elk bericht met dit voorvoegsel)


class Ontvanger:
    """Luistert op UDP 8001 en antwoordt de ESP32 met de ingest-URL."""

    def __init__(self, url, poort=POORT):
        self.url = url           # bv http://192.168.4.2:8000/api/ingest
        self.poort = poort
        self._sock = None
        self._thread = None
        self._stop = threading.Event()
        self._laatste_zoeker = None   # (ip, tijd) van de laatste zoeker

    def start(self):
        """Start de luisterthread; stilletjes als de poort al bezet is.

        Poort 0 betekent: kies zelf een vrije poort (handig in tests,
        zodat een draaiende dashboard nooit stoort).
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", self.poort))
        except OSError:
            sock.close()
            return False
        if self.poort == 0:
            self.poort = sock.getsockname()[1]
        sock.settimeout(0.5)
        self._sock = sock
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def _loop(self):
        while not self._stop.is_set():
            try:
                data, afzender = self._sock.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data or not data.startswith(VERBINDER):
                continue
            self._laatste_zoeker = afzender[0]
            try:
                self._sock.sendto(self.url.encode("utf-8"), afzender)
            except OSError:
                pass

    @property
    def laatste_zoeker(self):
        return self._laatste_zoeker

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None


def vind_dashboard(poort=POORT, timeout=1.0, zend_poort=0):
    """Zoek de dashboard vanaf de ESP32-zijde (hier: om het te testen).

    Stuurt één broadcast en wacht op het antwoord. Geeft de URL of None.
    In de firmware staat dezelfde logica in C++; dit is de leesbare versie
    die de tests gebruiken.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", zend_poort))
        sock.settimeout(timeout)
        doelen = (("255.255.255.255", poort), ("127.0.0.1", poort))
        for _ in range(3):
            # Per doel apart proberen: een mislukte broadcast (geen route,
            # VPN) mag de unicast niet meenemen.
            for doel in doelen:
                try:
                    sock.sendto(VERBINDER + b"?", doel)
                except OSError:
                    continue
            try:
                data, _ = sock.recvfrom(512)
                if data:
                    return data.decode("utf-8", errors="replace")
            except socket.timeout:
                continue
        return None
    finally:
        sock.close()
