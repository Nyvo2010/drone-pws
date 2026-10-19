"""Minimale tests voor Sauron — draaien zonder pytest/hardware.

Starten:  python3 tests/test_sauron.py
Bij falen: AssertionError + exit 1. Bij slagen: "ALLE TESTS OK".

Elke test gebruikt gesimuleerde data (nooit echte hardware), zodat ze
ook offline op elke laptop werken.
"""

import json
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, ".")  # run vanaf repo-root: import sauron...

from sauron import (autonomy, classify, geo, gps_nmea, pipeline, replay, server,
                    sim, state, thermal)
from sauron.config import DEFAULT
from sauron.flightlog import FlightRecorder
from sauron.tracking import FireTracker


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


def test_frame_met_ongeldige_waarden_is_fout():
    # Een kapot ESP32-pakket (NaN, inf, tekst) mag nooit stil als
    # "geen brand" doorgaan: de server moet er een 400 van maken.
    for waarde in (float("nan"), float("inf"), "heet"):
        frame = sim.make_frame()
        frame[10] = waarde
        try:
            thermal.find_hotspots(frame)
            raise SystemExit("FAIL: ongeldige waarde %r geaccepteerd" % (waarde,))
        except ValueError:
            pass  # verwacht


def test_agl_nul_meldt_brand_zonder_locatie():
    # Op de grond is er geen geldige driehoek. De brand moet wel gemeld
    # worden (met waarschuwing), maar zonder verzonnen coördinaten.
    frame = sim.make_frame(vlekken=[(20, 8, 85.0, 2.0)])
    r = pipeline.detect_event(frame, 52.09, 4.31, 90.0, 10.0, 10.0)
    assert r["n_fires"] == 1, "brand blijft zichtbaar op AGL 0"
    brand = r["fires"][0]
    assert brand["hotspot_lat"] is None and brand["hotspot_lon"] is None
    assert brand["afstand_m"] is None
    assert r["location_warning"], "operator krijgt uitleg waarom locatie mist"
    assert r["height_warning"], "AGL 0 valt buiten het testbereik"


def test_state_legt_tijdstippen_vast():
    # De UI toont per logregel het echte tijdstip; beide lijsten blijven
    # even lang, ook als de ringbuffer vol raakt.
    st = state.State()
    for i in range(70):
        st.add_log("regel %d" % i)
    assert len(st._log_times) == 50
    assert st._log_times == sorted(st._log_times)
    assert len(st._log_times) == len(st._logs)


def _brand(offset_lat=0.0):
    """Eén geclassificeerde brand uit de echte pipeline (vaste seed)."""
    resultaat = pipeline.detect_event(
        sim.make_frame(vlekken=[(20, 8, 85.0, 2.5)]),
        52.09, 4.31, 90.0, 25.0, 10.0,
    )
    brand = dict(resultaat["fires"][0])
    brand["hotspot_lat"] += offset_lat
    return brand


def test_tracking_zelfde_brand_geen_duplicaat():
    tracker = FireTracker()
    brand = _brand()
    eerste, events = tracker.update([brand], now=0.0)
    assert len(eerste) == 1
    assert eerste[0]["id"] == "B1"
    assert eerste[0]["observations"] == 1
    assert [e["type"] for e in events] == ["new"]

    # Zelfde brand, volgende frame: dezelfde track, geen nieuw ID.
    tweede, events = tracker.update([dict(brand)], now=1.0)
    assert len(tweede) == 1
    assert tweede[0]["id"] == "B1"
    assert tweede[0]["observations"] == 2
    assert events == [], "geen duplicaat en geen ruis-event"


def test_tracking_uit_beeld_en_terug():
    tracker = FireTracker()
    brand = _brand()
    tracker.update([brand], now=0.0)

    # Eén gemiste frame is nog binnen de grace-periode: geen "lost".
    binnen, events = tracker.update([], now=1.0)
    assert binnen[0]["status"] == "active"
    assert events == []

    # Na de grace-periode wel uit beeld, met het laatste tijdstip.
    uit, events = tracker.update([], now=3.0)
    assert uit[0]["status"] == "lost"
    assert uit[0]["last_seen"] == 0.0
    assert [e["type"] for e in events] == ["lost"]

    # Terug in beeld: dezelfde B1, geen nieuwe brand.
    terug, events = tracker.update([dict(brand)], now=4.0)
    assert len(terug) == 1
    assert terug[0]["id"] == "B1"
    assert terug[0]["status"] == "active"
    assert [e["type"] for e in events] == ["reacquired"]


def test_tracking_andere_locatie_is_nieuwe_brand():
    tracker = FireTracker()
    tracker.update([_brand()], now=0.0)
    ver_weg = _brand(offset_lat=0.001)  # ~111 m: ruim buiten de matchstraal
    ver_weg["x"] += 10                 # ook ver in beeld: echt een andere plek
    ver_weg["y"] += 5
    branden, _ = tracker.update([ver_weg], now=1.0)
    assert {b["id"] for b in branden} == {"B1", "B2"}


def test_tracking_geo_jitter_matcht_op_pixel():
    # De heetste pixel kan binnen een grote brand verspringen: de geo-locatie
    # schuift dan mee, maar de pixelpositie blijft dichtbij. Dat mag geen
    # nieuwe brand opleveren.
    tracker = FireTracker()
    brand = _brand()
    tracker.update([brand], now=0.0)
    verschoven = dict(brand)
    verschoven["hotspot_lat"] += 0.0002   # ~22 m: buiten de geo-matchstraal
    branden, _ = tracker.update([verschoven], now=1.0)
    assert len(branden) == 1
    assert branden[0]["id"] == "B1"


def test_tracking_zonder_locatie_matcht_op_pixel():
    tracker = FireTracker()
    brand = _brand()
    brand["hotspot_lat"] = None
    brand["hotspot_lon"] = None
    tracker.update([brand], now=0.0)
    tweede, _ = tracker.update([dict(brand)], now=1.0)
    assert len(tweede) == 1
    assert tweede[0]["id"] == "B1"


def test_tracking_archiveert_na_timeout():
    tracker = FireTracker()
    tracker.update([_brand()], now=0.0)
    over, events = tracker.update([], now=130.0)  # > 120 s archief-timeout
    assert over == []
    assert [e["type"] for e in events] == ["lost", "archived"]
    assert tracker.snapshot(131.0) == [], "gearchiveerd spoor niet meer tonen"


def test_state_telt_alleen_zichtbare_branden():
    # Een uit-beeld-track blijft voor herdetectie in de lijst staan, maar
    # telt niet mee als actieve brand in de thermische samenvatting.
    st = state.State()
    st.fires = [{"id": "B1", "active": True}, {"id": "B2", "active": False}]
    assert st.public_dict()["thermal"]["n_fires"] == 1


def test_vlucht_recorder_jsonl():
    with tempfile.TemporaryDirectory() as map_naam:
        recorder = FlightRecorder(map_naam)
        vlucht = recorder.start()
        assert Path(vlucht["file"]).is_file()
        recorder.record({"type": "log", "message": "hallo"})
        recorder.end("test")

        vluchten = recorder.list_flights()
        assert len(vluchten) == 1
        pad = recorder.path_for(vluchten[0]["name"])
        assert pad is not None
        regels = [json.loads(r) for r in pad.read_text().splitlines()]
        assert [r["type"] for r in regels] == [
            "flight_start", "log", "flight_end"]
        assert recorder.path_for("../evil.jsonl") is None


def test_app_logt_vlucht_en_reset():
    with tempfile.TemporaryDirectory() as map_naam:
        recorder = FlightRecorder(map_naam)
        app = server.App(recorder=recorder)
        frame = sim.make_frame(vlekken=[(20, 8, 85.0, 2.5)])
        drone = {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
                 "heading_deg": 90.0, "fix": 3, "sats": 9, "hdop": 0.8}
        uit = app.ingest(frame, drone, 10.0)
        assert uit["n_fires"] == 1
        assert uit["fires"][0]["id"] == "B1"
        assert app.snapshot()["flight"] is not None

        app.new_flight()
        staat = app.snapshot()
        assert staat["drone"]["lat"] is None
        assert staat["fires"] == []
        assert any("vlucht gestart" in regel for regel in staat["logs"])
        app.close()

        types = []
        for bestand in Path(map_naam).glob("*.jsonl"):
            types += [json.loads(r)["type"]
                      for r in bestand.read_text().splitlines()]
        assert "flight_start" in types
        assert "ingest" in types
        assert "flight_end" in types
        assert len(recorder.list_flights()) == 2


def test_server_api_eind_tot_eind():
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
        assert staat["last_update"] is not None, "UI kan versheid tonen"
        assert len(staat["log_times"]) == len(staat["logs"]), \
            "tijdstippen horen bij de logregels"
        with urllib.request.urlopen(basis + "/api/frame") as r:
            frame = json.loads(r.read().decode("utf-8"))
        assert len(frame["cells"]) == 768, "frame voor canvas"

        # Meting op de grond (AGL 0): brand melden zonder locatie mag
        # geen serverfout geven (de logregel crashte hier eerder op).
        body2 = json.dumps({
            "frame": sim.make_frame(vlekken=[(20, 8, 85.0, 2.5)]),
            "drone": {"lat": 52.09, "lon": 4.31,
                      "alt_msl": 10.0, "heading_deg": 90.0},
            "gps_alt_launch": 10.0,
        }).encode("utf-8")
        req2 = urllib.request.Request(basis + "/api/ingest", data=body2,
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req2) as r:
            antwoord2 = json.loads(r.read().decode("utf-8"))
        assert antwoord2["ok"] and antwoord2["n_fires"] == 1
        assert antwoord2["fires"][0]["hotspot_lat"] is None
        with urllib.request.urlopen(basis + "/api/state") as r:
            staat2 = json.loads(r.read().decode("utf-8"))
        assert staat2["warning"], "locatiewaarschuwing zichtbaar voor de UI"
        assert any("geen locatie" in line for line in staat2["logs"]), \
            "waarschuwing staat ook in het logboek"

        # Nieuwe vlucht: alles leeg, inclusief frame en branden.
        req3 = urllib.request.Request(basis + "/api/new-flight",
                                      data=b"", method="POST")
        with urllib.request.urlopen(req3) as r:
            antwoord3 = json.loads(r.read().decode("utf-8"))
        assert antwoord3["ok"]
        with urllib.request.urlopen(basis + "/api/state") as r:
            staat3 = json.loads(r.read().decode("utf-8"))
        assert staat3["drone"]["lat"] is None
        assert staat3["thermal"]["n_fires"] == 0
        assert staat3["fires"] == []
        assert any("vlucht gestart" in line for line in staat3["logs"])
        with urllib.request.urlopen(basis + "/api/flights") as r:
            vluchten = json.loads(r.read().decode("utf-8"))
        assert vluchten["flights"] == [], "geen recorder = geen bestanden"
    finally:
        srv.shutdown()


def test_state_log_is_ringbuffer():
    st = state.State()
    for i in range(70):
        st.add_log("regel %d" % i)
    assert len(st._logs) == 50, "max 50 regels bewaard"
    assert st._logs[-1] == "regel 69"


def test_dode_pixels_worden_geen_brand():
    # De MLX90640 heeft altijd een paar dode pixels (en een mislukte
    # I2C-read geeft uitschieters). Drie naast elkaar liggende kapotte
    # cellen mogen nooit als brand met coördinaten doorgaan.
    frame = sim.make_frame()
    for x, y in ((10, 10), (11, 10), (10, 11)):
        frame[y * DEFAULT.width + x] = 1200.0
    ambient, _, hotspots = thermal.find_hotspots(frame)
    assert ambient < 25.0, "kapotte cellen mogen de mediaan niet opblazen"
    assert hotspots == [], "dode pixels horen geen hotspot te zijn"

    # Ook het canvas krijgt de opgeschoonde waarden: anders schaalt de
    # kleurenkaart op 1200 C en lijkt de rest van het veld ijs.
    schoon = thermal.sanitize_frame(frame)
    assert max(schoon) < 100.0, "uitschieter is vervangen door de mediaan"
    assert len(schoon) == DEFAULT.width * DEFAULT.height

    # Een echte brand naast een dood pixel blijft gewoon gevonden worden.
    frame[20 * DEFAULT.width + 20] = 85.0
    frame[19 * DEFAULT.width + 20] = 80.0
    frame[20 * DEFAULT.width + 21] = 78.0
    _, _, hotspots = thermal.find_hotspots(frame)
    assert len(hotspots) == 1, "echte brand blijft zichtbaar"


def test_zwakke_fix_geeft_geen_locatie():
    # fix 0/1 = geen betrouwbare 3D-positie. De brand moet wel gemeld
    # worden, maar zonder verzonnen coördinaten.
    frame = sim.make_frame(vlekken=[(20, 8, 85.0, 2.0)])
    for fix in (0, 1):
        r = pipeline.detect_event(frame, 52.09, 4.31, 90.0, 25.0, 10.0,
                                  gps_fix=fix)
        assert r["n_fires"] == 1
        assert r["fires"][0]["hotspot_lat"] is None
        assert "fix" in r["location_warning"]
    # Met een 3D-fix komt de locatie gewoon terug.
    r = pipeline.detect_event(frame, 52.09, 4.31, 90.0, 25.0, 10.0,
                              gps_fix=3)
    assert r["fires"][0]["hotspot_lat"] is not None


def test_ongeldige_positie_geeft_geen_locatie():
    # Zonder fix stuurt de firmware vaak 0.0/0.0: geldige getallen, maar
    # geen positie. Die mag nooit coördinaten bij de Gulf of Guinea geven.
    frame = sim.make_frame(vlekken=[(20, 8, 85.0, 2.0)])
    r = pipeline.detect_event(frame, 0.0, 0.0, 90.0, 25.0, 10.0)
    assert r["fires"][0]["hotspot_lat"] is None
    assert r["location_warning"], "operator krijgt uitleg"


def test_ontbrekende_hoogte_is_geen_crash():
    # Een packet zonder GPS-hoogte mag de frame niet weggooien: de
    # detectie werkt door, alleen de locatie ontbreekt.
    frame = sim.make_frame(vlekken=[(20, 8, 85.0, 2.0)])
    r = pipeline.detect_event(frame, 52.09, 4.31, 90.0, None, None)
    assert r["n_fires"] == 1
    assert r["agl_m"] is None and r["height_warning"] is None
    assert r["fires"][0]["hotspot_lat"] is None
    assert "hoogte" in r["location_warning"]


def test_ingest_tolerant_voor_firmware_verschillen():
    # De firmware is van een teamgenoot en gaat morgen voor het eerst
    # live: kleine naamverschillen en een genest frame mogen geen 400 zijn.
    app = server.App()
    frame = sim.make_frame(vlekken=[(20, 8, 85.0, 2.5)])
    genest = [frame[r * 32:(r + 1) * 32] for r in range(24)]

    # Geen lanceerhoogte, andere veldnamen, genest frame.
    uit = app.ingest_body({
        "temps": genest,
        "drone": {"latitude": 52.09, "longitude": 4.31,
                  "alt": 25.0, "yaw": 90.0, "fix": 3},
    })
    assert uit["n_fires"] == 1, "frame is verwerkt, niet geweigerd"
    assert uit["fires"][0]["hotspot_lat"] is None, "zonder hoogte geen locatie"
    assert any("lanceerhoogte" in regel for regel in app.state._logs)

    # Tweede frame mét hoogte: nu wel coördinaten.
    uit = app.ingest_body({
        "frame": frame, "gps_alt_launch": 10.0,
        "drone": {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
                  "heading_deg": 90.0, "fix": 3},
    })
    assert uit["fires"][0]["hotspot_lat"] is not None

    # Derde frame zonder hoogte: de eerder ontvangen waarde wordt hergebruikt.
    uit = app.ingest_body({
        "frame": frame,
        "drone": {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
                  "heading_deg": 90.0, "fix": 3},
    })
    assert uit["fires"][0]["hotspot_lat"] is not None


def test_server_logt_afgewezen_ingest():
    # Zonder deze melding zie je in het veld alleen "niet verbonden"
    # terwijl de ESP32 intussen 400's staat te vangen.
    from http.server import ThreadingHTTPServer
    from urllib.error import HTTPError

    app = server.App()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(app))
    draad = threading.Thread(target=srv.serve_forever, daemon=True)
    draad.start()
    basis = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        req = urllib.request.Request(basis + "/api/ingest",
                                     data=b'{"drone": {}}',
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
            raise SystemExit("FAIL: ingest zonder frame moet 400 geven")
        except HTTPError as fout:
            assert fout.code == 400
        with urllib.request.urlopen(basis + "/api/state") as r:
            staat = json.loads(r.read().decode("utf-8"))
        assert any("ingest afgewezen" in regel for regel in staat["logs"]), \
            "afwijzing staat in het logboek"
    finally:
        srv.shutdown()


def test_capture_bewaart_ruwe_frames():
    with tempfile.TemporaryDirectory() as map_naam:
        recorder = FlightRecorder(map_naam, capture_frames=True)
        app = server.App(recorder=recorder)
        app.ingest(sim.make_frame(vlekken=[(20, 8, 85.0, 2.5)]),
                   {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
                    "heading_deg": 90.0, "fix": 3}, 10.0)
        app.close()
        pad = Path(map_naam) / recorder.list_flights()[0]["name"]
        frames = replay.load_frames(str(pad))
        assert len(frames) == 1, "ingest-regel met cells is leesbaar"
        assert len(frames[0]) == 768
        assert replay.tel_buiten_bereik(frames[0]) == 0


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
