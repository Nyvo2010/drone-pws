"""Minimale tests voor Sauron — draaien zonder pytest/hardware.

Starten:  python3 tests/test_sauron.py
Bij falen: AssertionError + exit 1. Bij slagen: "ALLE TESTS OK".

Elke test gebruikt gesimuleerde data (nooit echte hardware), zodat ze
ook offline op elke laptop werken.
"""

import sys
import threading
import urllib.request

sys.path.insert(0, ".")  # run vanaf repo-root: import sauron...

from sauron import autonomy, classify, geo, gps_nmea, pipeline, server, sim, state, thermal
from sauron.config import DEFAULT


def test_matrix_vorm_en_validatie():
    m = thermal.frame_to_matrix(sim.make_frame())
    assert len(m) == 24 and len(m[0]) == 32, "matrix moet 24x32 zijn"
    try:
        thermal.frame_to_matrix([1.0] * 10)
        raise SystemExit("FAIL: korte lijst moet ValueError geven")
    except ValueError:
        pass  # verwacht: kapotte pakketten nooit stil accepteren


def test_ambient_is_mediaan():
    # Eén hete pixel mag de mediaan niet meetrekken (wel het gemiddelde).
    # Exact uniforme lijst (geen ruis) voor een exacte assert.
    frame = [20.0] * (DEFAULT.width * DEFAULT.height)
    frame[0] = 500.0
    m = thermal.frame_to_matrix(frame)
    assert thermal.estimate_ambient(m) == 20.0, "mediaan moet 20.0 blijven"


def test_vlek_wordt_gevonden():
    ambient, drempel, hotspots = thermal.find_hotspots(
        sim.make_frame(vlekken=[(20, 8, 85.0, 2.0)]))
    assert len(hotspots) >= 1, "vlek van 85 C moet gevonden worden"
    heetste = hotspots[0]
    assert abs(heetste["x"] - 20) <= 1 and abs(heetste["y"] - 8) <= 1
    assert heetste["max_temp"] > 80.0
    assert ambient < 25.0, "ambient mag niet door de brand omhoog"


def test_leeg_veld_geen_hotspot():
    # Uniform warm (28 C zomerdag) maar nergens een UITschieter -> niets.
    _, _, hotspots = thermal.find_hotspots(sim.make_frame(ambient=28.0))
    assert hotspots == [], "uniform veld mag geen hotspots geven"


def test_classificatie_brand_en_geen_brand():
    brand = classify.classify_hotspot({"max_temp": 85.0, "area": 10}, 22.0)
    assert brand["is_fire"], "85 C bij 22 C omgeving = brand"
    assert set(brand["reasons"]) == {"stijging_boven_omgeving",
                                     "absoluut_warm_genoeg", "groot_genoeg"}
    koud = classify.classify_hotspot({"max_temp": 30.0, "area": 10}, 22.0)
    assert not koud["is_fire"], "8 C stijging is te weinig voor brand"


def test_meerdere_hotspots_gesorteerd():
    frame = sim.make_frame(vlekken=[(10, 10, 60.0, 2.0), (25, 15, 95.0, 2.0)])
    _, _, hotspots = thermal.find_hotspots(frame)
    assert len(hotspots) >= 2, "twee vlekken = twee hotspots"
    assert hotspots[0]["max_temp"] >= hotspots[1]["max_temp"], "heetste eerst"


def test_nmea_gga():
    zin = "$GPGGA,123519,5205.4000,N,00418.6000,E,1,08,0.9,25.0,M,0.0,M,,*47"
    p = gps_nmea.parse_line(zin)
    assert p is not None
    assert abs(p["lat"] - (52 + 5.4 / 60)) < 1e-6, "52d05.4' N"
    assert abs(p["lon"] - (4 + 18.6 / 60)) < 1e-6, "4d18.6' E"
    assert p["alt_msl"] == 25.0


def test_agl_en_hoogtewaarschuwing():
    assert geo.agl_from_gps(25.0, 10.0) == 15.0, "25 - 10 = 15 m AGL"
    assert geo.check_height(15.0) is None, "15 m is binnen bereik"
    assert geo.check_height(3.0) is not None, "3 m moet waarschuwen"
    assert geo.check_height(40.0) is not None, "40 m moet waarschuwen"


def test_recht_erboven_is_dronepositie():
    # Centrum-pixel -> hoeken ~0 -> hotspot vrijwel gelijk aan drone.
    loc = geo.locate_hotspot(52.0, 4.3, 90.0, 15.0, 16, 12)
    assert loc["afstand_m"] < 1.0, "centrum zit (bijna) recht onder de drone"
    dlat = abs(loc["hotspot_lat"] - 52.0)
    dlon = abs(loc["hotspot_lon"] - 4.3)
    assert dlat < 1e-5 and dlon < 1e-5


def test_pixel_vooruit_schuift_noord():
    # Pixel aan de voorrand (rij 0), heading noord: hotspot noordelijker.
    loc = geo.locate_hotspot(52.0, 4.3, 0.0, 15.0, 16, 0)
    assert loc["noord_m"] > 5.0, "voorrand moet meters vooruit liggen"
    assert loc["hotspot_lat"] > 52.0


def test_pipeline_eind_tot_eind():
    frame = sim.make_frame(vlekken=[(20, 8, 85.0, 2.0)])
    r = pipeline.detect_event(frame, 52.09, 4.31, 90.0, 25.0, 10.0)
    assert r["n_fires"] == 1, "verwacht precies 1 brand, kreeg %d" % r["n_fires"]
    brand = r["fires"][0]
    assert "hotspot_lat" in brand and "hotspot_lon" in brand
    assert brand["afstand_m"] > 0, "vlek zit niet in het centrum"
    r2 = pipeline.detect_event(sim.make_frame(ambient=28.0),
                               52.09, 4.31, 90.0, 25.0, 10.0)
    assert r2["n_fires"] == 0, "leeg veld mag geen brand geven"


def test_server_api_eind_tot_eind():
    import json
    from http.server import ThreadingHTTPServer
    # Server op een vrije poort, in een thread, met echte HTTP-aanroepen.
    app = server.App()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(app))
    poort = srv.server_address[1]
    draad = threading.Thread(target=srv.serve_forever, daemon=True)
    draad.start()
    basis = "http://127.0.0.1:%d" % poort
    try:
        with urllib.request.urlopen(basis + "/") as r:
            assert "Sauron" in r.read().decode("utf-8"), "dashboard-HTML"
        body = json.dumps({
            "frame": sim.make_frame(vlekken=[(20, 8, 85.0, 2.5)]),
            "drone": {"lat": 52.09, "lon": 4.31,
                      "alt_msl": 25.0, "heading_deg": 90.0},
            "gps_alt_launch": 10.0,
        }).encode("utf-8")
        req = urllib.request.Request(basis + "/api/ingest", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            antwoord = json.loads(r.read().decode("utf-8"))
        assert antwoord["ok"] and antwoord["n_fires"] == 1
        with urllib.request.urlopen(basis + "/api/state") as r:
            staat = json.loads(r.read().decode("utf-8"))
        assert staat["thermal"]["n_fires"] == 1, "staat bevat de brand"
        assert staat["battery"] is None, "batterij is placeholder (None)"
        assert staat["autonomy"]["enabled"] is False, "autonomie uit"
        assert len(staat["logs"]) >= 1, "brand is gelogd"
        with urllib.request.urlopen(basis + "/api/frame") as r:
            frame = json.loads(r.read().decode("utf-8"))
        assert len(frame["cells"]) == 768, "frame voor canvas"
    finally:
        srv.shutdown()


def test_state_log_is_ringbuffer():
    st = state.State()
    for i in range(70):
        st.add_log("regel %d" % i)
    assert len(st._logs) == 50, "max 50 regels bewaard"
    assert st._logs[-1] == "regel 69"


def test_autonomie_stub_is_uit():
    advies = autonomy.suggest_action(state.State())
    assert advies["enabled"] is False, "stub meldt zichzelf als uit"
    assert advies["action"] == "hold", "veilige default: hold"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main():
    for test in TESTS:
        test()
        print("ok - %s" % test.__name__)
    print("ALLE TESTS OK (%d)" % len(TESTS))


if __name__ == "__main__":
    main()
