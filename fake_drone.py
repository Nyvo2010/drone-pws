"""Nep-drone: de firmware simuleren zonder hardware.

Dit is de Python-tegenhanger van `firmware/sauron_poster.h`. Hetzelfde
gedrag, dezelfde JSON, dezelfde ontdekking — zodat de dashboard (en het
contract met de teamgenoot) getest kunnen worden terwijl de echte ESP32
nog geflasht wordt.

Gedrag van de firmware dat hier één-op-één nagemaakt wordt:
  1. broadcast "SAURON?" tot er een ingest-URL terugkomt;
  2. elke seconde een frame van 768 temperaturen POSTen;
  3. bij een mislukte POST het doel wissen en opnieuw zoeken;
  4. GPS is optioneel (zonder: brand zonder coördinaten + waarschuwing).

Gebruik:
  python3 fake_drone.py                    # nep-brand, met GPS
  python3 fake_drone.py --no-gps           # zoals firmware zonder UART4
  python3 fake_drone.py --interval 0.5     # sneller

Stoppen: Ctrl+C.
"""

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request

from sauron import discover, sim

DRONE = {"lat": 52.090000, "lon": 4.310000, "alt_msl": 25.0,
         "heading_deg": 90.0, "fix": 3, "sats": 12, "hdop": 0.9}
ALT_LANCERING = 10.0


def zoek_doel(udp_poort, pogingen=3, wachttijd=0.35):
    """Net als sauronVindDoel(): broadcasten tot er een antwoord komt."""
    for _ in range(pogingen):
        url = discover.vind_dashboard(poort=udp_poort, timeout=wachttijd)
        if url:
            return url
        time.sleep(wachttijd)
    return None


def bouw_payload(t, met_gps):
    """De body zoals sauronBouwBody() die bouwt (rij-majeur 32x24)."""
    x = 16 + 6 * math.sin(t * 0.3)
    # 250 C: een echte brand leest op 15 m AGL honderden graden; 85 C zou
    # volgens de huidige drempels "verdacht" zijn en geen brand melden.
    frame = sim.make_frame(vlekken=[(x, 10, 250.0, 2.5)], seed=t)
    payload = {"frame": frame}
    if met_gps:
        payload["drone"] = DRONE
        payload["gps_alt_launch"] = ALT_LANCERING
    return payload


def post(url, payload, timeout=3.0):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Nep-drone (firmware-simulator)")
    parser.add_argument("--udp-poort", type=int, default=discover.POORT,
                        help="poort waarop de laptop luistert (8001)")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="seconden tussen twee frames (firmware: 1.0)")
    parser.add_argument("--no-gps", action="store_true",
                        help="zonder GPS, net als firmware zonder UART4")
    args = parser.parse_args()

    print("nep-drone gestart (Ctrl+C om te stoppen)")
    doel = None
    t = 0.0
    while True:
        if doel is None:
            doel = zoek_doel(args.udp_poort)
            if doel is None:
                print("  dashboard niet gevonden op udp/%d ..." % args.udp_poort)
                time.sleep(1.0)
                continue
            print("  dashboard gevonden: %s" % doel)

        try:
            antwoord = post(doel, bouw_payload(t, not args.no_gps))
            print("  frame %5.1fs -> ok=%s n_fires=%s"
                  % (t, antwoord.get("ok"), antwoord.get("n_fires")))
        except urllib.error.HTTPError as fout:
            # Zoals in de firmware: mislukte POST -> doel wissen en
            # opnieuw ontdekken (het IP van de laptop kan veranderd zijn).
            print("  POST mislukt (HTTP %d), opnieuw zoeken" % fout.code)
            doel = None
        except (urllib.error.URLError, OSError) as fout:
            print("  POST mislukt (%s), opnieuw zoeken" % fout)
            doel = None

        t += args.interval
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nnep-drone gestopt")
        sys.exit(0)
