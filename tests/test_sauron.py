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

from sauron import (autonomy, classify, esp32, geo, gps_nmea, pipeline, replay,
                    server, sim, state, thermal)
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
        sim.make_frame(vlekken=[(20, 8, 250.0, 2.0)]))
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
    # Echte brandtemperatuur: een kampvuur op 15 m AGL leest honderden
    # graden in de heetste pixel.
    brand = classify.classify_hotspot({"max_temp": 250.0, "area": 10}, 22.0)
    assert brand["is_fire"], "250 C bij 22 C omgeving = brand"
    assert brand["level"] == "fire"
    assert set(brand["reasons"]) == {"sprong_boven_omgeving",
                                     "absoluut_heet", "lokale_sprong",
                                     "hete_kern", "geen_ruis"}
    koud = classify.classify_hotspot({"max_temp": 30.0, "area": 10}, 22.0)
    assert not koud["is_fire"], "8 C stijging is te weinig voor brand"
    assert koud["level"] == "noise"


def test_steen_is_geen_brand():
    # Dit is de veldfout van 30 okt: een zonverwarmde steen (43 C bij een
    # omgeving van 26 C) werd als brand gemeld. Zonverwarmde stenen,
    # dakpannen en asfalt halen 55-70 C, dus alleen absolute hitte plus
    # een grote sprong boven de omgeving telt als brand.
    steen = classify.classify_hotspot({"max_temp": 43.1, "area": 3}, 25.9)
    assert not steen["is_fire"], "steen van 43 C is geen brand"
    assert steen["level"] == "noise"

    warme_steen = classify.classify_hotspot({"max_temp": 64.0, "area": 9}, 25.0)
    assert not warme_steen["is_fire"], "zonverwarmde steen van 64 C is geen brand"
    assert warme_steen["level"] == "suspect", "wel een verdacht warm voorwerp"

    # Een echt brandje dichtbij (bijna volle pixel) is wel een brand.
    vuur = classify.classify_hotspot({"max_temp": 180.0, "area": 4}, 25.0)
    assert vuur["is_fire"]


def test_echte_brand_onder_90_c_is_toch_brand():
    # Velddata 11 nov: een kampvuur op 1 m las 49-116 C in de heetste pixel
    # (hoogste meting van een hele vlucht: 89.4 C). Met alleen de 90 C-regel
    # bleef dat 34 frames lang "verdacht" en kwam er geen brandmelding. Een
    # sprong van 60 C boven de omgeving kan geen steen of dakpan maken.
    heet = classify.classify_hotspot({"max_temp": 89.4, "area": 6}, 10.2)
    assert heet["is_fire"], heet
    assert heet["reasons"]["absoluut_heet"] is False
    assert heet["reasons"]["sprong_boven_omgeving"] is True

    # Zonverwarmde steen bij 20 C lucht: 44 C sprong is nog steeds geen vuur.
    steen = classify.classify_hotspot({"max_temp": 64.0, "area": 9}, 20.0)
    assert steen["level"] == "suspect", steen

    # Hoogte: een vlam die minder dan een cel vult leest maar ~85 C, terwijl
    # het veld 12 C is. Die sprong is een vuur, ook met één pixel en zonder
    # dat de absolute 90 C-grens gehaald wordt.
    pixel = classify.classify_hotspot({"max_temp": 85.0, "area": 1}, 12.0)
    assert pixel["is_fire"], pixel
    assert pixel["reasons"]["geen_ruis"] is True
    assert pixel["reasons"]["absoluut_heet"] is False

    # Een enkele cel die maar 25 C boven de omgeving zit blijft ruis.
    lauw = classify.classify_hotspot({"max_temp": 37.0, "area": 1}, 12.0)
    assert lauw["level"] == "noise", lauw


def test_heet_gebied_boven_sensorgrens_is_geen_leesfout():
    # Log 11 nov 14:07: het heetste frame van een echte brand bevatte 640 C
    # (heter dan de sensor kan uitdrukken). Dat werd door de mediaan
    # vervangen en leverde nul hotspots op, terwijl het bord zelf "fire"
    # meldde. Een groot aaneengesloten gebied is een bron, geen leesfout.
    frame = [10.0] * 768
    for y in (10, 11, 12):
        for x in (14, 15, 16):
            frame[y * DEFAULT.width + x] = 640.0
    ambient, _, hotspots = thermal.find_hotspots(frame)
    assert len(hotspots) == 1, hotspots
    assert hotspots[0]["max_temp"] == DEFAULT.valid_temp_max_c
    assert hotspots[0]["area"] == 9
    assert classify.classify_hotspot(hotspots[0], ambient)["is_fire"]

    # Drie losse cellen (de flarden van 30 okt) blijven sensorruis.
    flard = [10.0] * 768
    for x, y in ((10, 10), (11, 10), (10, 11)):
        flard[y * DEFAULT.width + x] = 640.0
    assert thermal.find_hotspots(flard)[2] == []


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
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.0)])
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
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.0)])
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
        sim.make_frame(vlekken=[(20, 8, 250.0, 2.5)]),
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
    assert eerste[0]["confirmed"] is False, "één frame is nog niet bevestigd"
    assert [e["type"] for e in events] == ["new"]

    # Zelfde brand, volgende frame: dezelfde track, geen nieuw ID, en na
    # twee metingen is de track bevestigd.
    tweede, events = tracker.update([dict(brand)], now=1.0)
    assert len(tweede) == 1
    assert tweede[0]["id"] == "B1"
    assert tweede[0]["observations"] == 2
    assert tweede[0]["confirmed"] is True
    assert [e["type"] for e in events] == ["confirmed"]


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
    assert terug[0]["confirmed"] is True
    assert [e["type"] for e in events] == ["reacquired", "confirmed"]


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


def _ander(frame, delta=0.1):
    """Kopie met één cel iets anders: een échte nieuwe meting.

    Twee identieke frames gelden bewust niet als twee metingen (bevroren
    sensorread of dubbel afgeleverd antwoord), dus tests die bevestiging
    willen moeten een nieuwe meting sturen — precies zoals de sensor dat
    zelf doet.
    """
    kopie = list(frame)
    kopie[0] = kopie[0] + delta
    return kopie


def test_app_logt_vlucht_en_reset():
    with tempfile.TemporaryDirectory() as map_naam:
        recorder = FlightRecorder(map_naam)
        app = server.App(recorder=recorder)
        assert app.snapshot()["flight_active"] is False, \
            "nog geen vlucht tot de operator er een start"
        app.start_flight("testvlucht")
        frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.5)])
        drone = {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
                 "heading_deg": 90.0, "fix": 3, "sats": 9, "hdop": 0.8}
        eerste = app.ingest(frame, drone, 10.0)
        assert eerste["n_fires"] == 0, "één frame is nog niet bevestigd"
        assert eerste["fires"][0]["confirmed"] is False
        uit = app.ingest(_ander(frame), drone, 10.0)
        assert uit["n_fires"] == 1
        assert uit["fires"][0]["id"] == "B1"
        assert uit["fires"][0]["confirmed"] is True
        assert uit["seq"] == 2, "elk frame krijgt een volgnummer"
        vlucht = app.snapshot()["flight"]
        assert vlucht is not None
        assert vlucht["name"] == "testvlucht"

        app.stop_flight()
        gestopt = app.snapshot()
        assert gestopt["flight_active"] is False, "stoppen sluit de vlucht"
        assert gestopt["flight"] is None
        assert any("vlucht gestopt: testvlucht" in regel
                   for regel in gestopt["logs"])

        app.new_flight("tweede vlucht")
        staat = app.snapshot()
        assert staat["flight_active"] is True
        assert staat["drone"]["lat"] is None
        assert staat["fires"] == []
        assert any("vlucht gestart: tweede vlucht" in regel
                   for regel in staat["logs"])
        app.close()

        types = []
        namen = []
        for bestand in Path(map_naam).glob("*.jsonl"):
            regels = [json.loads(r) for r in bestand.read_text().splitlines()]
            types += [r["type"] for r in regels]
            namen += [r.get("flight", {}).get("name") for r in regels
                      if r["type"] == "flight_start"]
        assert "flight_start" in types
        assert "ingest" in types
        assert "flight_end" in types
        assert sorted(namen) == ["testvlucht", "tweede vlucht"], \
            "de vluchtnaam staat in het logbestand"
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
        thermisch = sim.make_frame(vlekken=[(20, 8, 250.0, 2.5)])
        drone = {"lat": 52.09, "lon": 4.31,
                 "alt_msl": 25.0, "heading_deg": 90.0}
        # Twee frames: een brand is pas bevestigd na twee metingen, en het
        # tweede frame is een nieuwe meting (identieke frames tellen niet).
        antwoord = None
        for meting_nr in range(2):
            meting = list(thermisch)
            meting[0] += 0.1 * meting_nr
            body = json.dumps({"frame": meting, "drone": drone,
                               "gps_alt_launch": 10.0}).encode("utf-8")
            req = urllib.request.Request(
                basis + "/api/ingest", data=body,
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
        laag = list(thermisch)
        laag[0] += 0.2
        body2 = json.dumps({
            "frame": laag,
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


def test_note_link_zonder_warmtebeeld():
    # De warmtecamera kan stuk zijn terwijl WiFi en GPS leven. Dan moet het
    # dashboard tóch "verbonden" zijn en de positie/fix tonen; er mag geen
    # frame verzonnen worden.
    app = server.App()
    try:
        assert app.state.last_update is None
        app.note_link(
            link={"latency_ms": 11.0, "ok_pct": 100.0},
            drone={"lat": 52.09, "lon": 4.31, "fix": 0, "sats": 0,
                   "age_s": 0.4},
        )
        staat = app.snapshot()
        assert staat["last_update"] is not None, "link-update = verbonden"
        assert staat["drone"]["lat"] == 52.09
        assert staat["drone"]["fc_sats"] == 0
        assert staat["link"]["latency_ms"] == 11.0
        assert app.frame_payload()["cells"] is None, "geen frame verzinnen"
        assert any("warmtecamera" in line for line in staat["logs"]), \
            "de reden staat in het logboek"
    finally:
        app.close()


def test_gps_aanvullen_uit_status():
    # De firmware zet fix_type ook als de gnssFixOK-bit laag is (live gezien:
    # fix_type 3, satellites 4, location_valid false). Alleen bij
    # location_valid=true mag die fix overgenomen worden; het aantal
    # satellieten is ook zonder fix eerlijk.
    gps = {"data_seen": True, "location_valid": False, "fix": 0, "sats": -1,
           "lat": None, "lon": None}
    geen_fix = {"fix_type": 3, "satellites": 4, "location_valid": False}
    uit = esp32.gps_aanvullen(gps, geen_fix)
    assert uit["fix"] == 0, "geen geldige fix: geen 3D tonen"
    assert uit["sats"] == 4, "satellieten tellen wel"
    assert uit["lat"] is None, "geen coördinaten verzinnen"
    # Met location_valid neemt het dashboard de ruwe UBX-fix over, zodat
    # gps_velden hem precies één keer omrekent (3D blijft 3D).
    wel = dict(geen_fix, location_valid=True)
    uit = esp32.gps_aanvullen(gps, wel)
    assert uit["fix"] == 3, "ruwe UBX-waarde; omrekenen gebeurt later"
    assert esp32.gps_velden(uit)["fix"] == 2, "3D op de dashboardschaal"
    # Een echte positie in /api/gps wint van de status.
    echt = {"fix": 2, "sats": 9}
    assert esp32.gps_aanvullen(echt, geen_fix) == echt


def test_geen_verse_gps_wordt_geen_fix():
    # /api/gps geeft fix -1 zodra de laatste update > 2 s oud is. Dat mag de
    # UI niet als "-1" tonen en zeker niet als fix tellen.
    assert esp32.normaliseer_fix(-1) == 0
    assert esp32.gps_velden({"fix": -1, "sats": -1})["fix"] == 0


def test_gps_velden_normaliseert_ubx_fix():
    # UBX fixType 3 = 3D, maar op de dashboardschaal is 3 "rtk". Zonder
    # omrekening zou een 2D-fix als 3D doorgaan en AGL/coördinaten geven.
    assert esp32.gps_velden({"fix": 3})["fix"] == 2
    assert esp32.gps_velden({"fix": "2"})["fix"] == 1
    assert esp32.gps_velden({"fix": 3}, normaliseer=False)["fix"] == 3
    assert esp32.gps_velden(None) == {}


def test_state_log_is_ringbuffer():
    st = state.State()
    for i in range(70):
        st.add_log("regel %d" % i)
    assert len(st._logs) == 50, "max 50 regels bewaard"
    assert st._logs[-1] == "regel 69"


def test_dode_pixels_worden_geen_brand():
    # De MLX90640 heeft altijd een paar dode pixels (en een mislukte
    # I2C-read geeft uitschieters). Drie naast elkaar liggende kapotte
    # cellen mogen nooit als brand met coördinaten doorgaan. 565 C is de
    # waarde die op 30 okt in het echt als "brand" doorkwam; 1200 C is de
    # klassieke I2C-flard.
    for waarde in (565.0, 1200.0):
        frame = sim.make_frame()
        for x, y in ((10, 10), (11, 10), (10, 11)):
            frame[y * DEFAULT.width + x] = waarde
        ambient, _, hotspots = thermal.find_hotspots(frame)
        assert ambient < 25.0, "kapotte cellen mogen de mediaan niet opblazen"
        assert hotspots == [], "dode pixels horen geen hotspot te zijn"

        # Ook het canvas krijgt de opgeschoonde waarden: anders schaalt de
        # kleurenkaart op 1200 C en lijkt de rest van het veld ijs.
        schoon = thermal.sanitize_frame(frame)
        assert max(schoon) < 100.0, "uitschieter is vervangen door de mediaan"
        assert len(schoon) == DEFAULT.width * DEFAULT.height

    # Een echte brand naast een dood pixel blijft gewoon gevonden worden.
    frame = sim.make_frame()
    frame[0] = 1200.0
    frame[20 * DEFAULT.width + 20] = 250.0
    frame[19 * DEFAULT.width + 20] = 180.0
    frame[20 * DEFAULT.width + 21] = 150.0
    _, _, hotspots = thermal.find_hotspots(frame)
    assert len(hotspots) == 1, "echte brand blijft zichtbaar"


def test_zwakke_fix_geeft_geen_locatie():
    # fix 0/1 = geen betrouwbare 3D-positie. De brand moet wel gemeld
    # worden, maar zonder verzonnen coördinaten.
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.0)])
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
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.0)])
    r = pipeline.detect_event(frame, 0.0, 0.0, 90.0, 25.0, 10.0)
    assert r["fires"][0]["hotspot_lat"] is None
    assert r["location_warning"], "operator krijgt uitleg"


def test_ontbrekende_hoogte_is_geen_crash():
    # Een packet zonder GPS-hoogte mag de frame niet weggooien: de
    # detectie werkt door, alleen de locatie ontbreekt.
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.0)])
    r = pipeline.detect_event(frame, 52.09, 4.31, 90.0, None, None)
    assert r["n_fires"] == 1
    assert r["agl_m"] is None and r["height_warning"] is None
    assert r["fires"][0]["hotspot_lat"] is None
    assert "hoogte" in r["location_warning"]


def test_ingest_tolerant_voor_firmware_verschillen():
    # De firmware is van een teamgenoot en gaat morgen voor het eerst
    # live: kleine naamverschillen en een genest frame mogen geen 400 zijn.
    app = server.App()
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.5)])
    genest = [frame[r * 32:(r + 1) * 32] for r in range(24)]

    # Geen lanceerhoogte, andere veldnamen, genest frame.
    uit = app.ingest_body({
        "temps": genest,
        "drone": {"latitude": 52.09, "longitude": 4.31,
                  "alt": 25.0, "yaw": 90.0, "fix": 3},
    })
    assert len(uit["fires"]) == 1, "frame is verwerkt, niet geweigerd"
    assert uit["n_fires"] == 0, "nog niet bevestigd na één frame"
    assert uit["fires"][0]["hotspot_lat"] is None, "zonder hoogte geen locatie"
    assert any("lanceerhoogte" in regel for regel in app.state._logs)

    # Tweede frame mét hoogte: nu wel coördinaten.
    uit = app.ingest_body({
        "frame": _ander(frame), "gps_alt_launch": 10.0,
        "drone": {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
                  "heading_deg": 90.0, "fix": 3},
    })
    assert uit["fires"][0]["hotspot_lat"] is not None

    # Derde frame zonder hoogte: de eerder ontvangen waarde wordt hergebruikt.
    uit = app.ingest_body({
        "frame": _ander(frame, 0.2),
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
        app.start_flight("capture")
        app.ingest(sim.make_frame(vlekken=[(20, 8, 250.0, 2.5)]),
                   {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
                    "heading_deg": 90.0, "fix": 3}, 10.0)
        app.close()
        pad = Path(map_naam) / recorder.list_flights()[0]["name"]
        frames = replay.load_frames(str(pad))
        assert len(frames) == 1, "ingest-regel met cells is leesbaar"
        assert len(frames[0]) == 768
        assert replay.tel_buiten_bereik(frames[0]) == 0


def test_esp32_contract_van_de_firmware():
    # Exact het antwoord van de firmware in "Info from esp PWS (temporary)":
    # UBX fixType, JSON-null voor dode pixels, en gps_alt_launch die nooit
    # wordt meegestuurd (sauronSetLaunchMsl wordt niet aangeroepen).
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.5)])
    frame[400] = None
    data = {
        "thermal_available": True,
        "frame": frame,
        "thermal": {"min_c": 12.0, "max_c": 85.0,
                    "hotspot": {"x": 20, "y": 8}},
        "drone": {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
                  "heading_deg": 90.0, "fix": 3, "sats": 12, "hdop": 0.9},
    }
    gps = {"data_seen": True, "location_valid": True, "lat": 52.09,
           "lon": 4.31, "alt_msl": 25.0, "heading_deg": 90.0,
           "speed_mps": 2.0, "fix": 3, "sats": 12, "hdop": 0.9}

    body = esp32.parse_data(data, gps)
    assert body is not None, "null-cel mag het frame niet weggooien"
    assert body["drone"]["fix"] == 2, "UBX 3D -> dashboardschaal 3D"

    app = server.App()
    # Eerste 3D-fix = lanceerpunt: AGL 0, dus nog geen coördinaten. Eén
    # frame is nog niet genoeg: de track blijft "verdacht".
    uit = app.ingest_body(body)
    assert len(uit["fires"]) == 1
    assert uit["n_fires"] == 0
    assert uit["fires"][0]["confirmed"] is False
    assert uit["agl_m"] == 0.0
    assert any("lanceerhoogte automatisch" in regel
               for regel in app.state._logs)

    # Tweede frame met dezelfde vlek: nu pas bevestigd.
    uit = app.ingest_body(dict(body, frame=_ander(body["frame"])))
    assert uit["n_fires"] == 1

    # Tien meter hoger: dezelfde brand krijgt nu wel coördinaten.
    hoger = dict(data, drone=dict(data["drone"], alt_msl=35.0),
                 frame=_ander(data["frame"], 0.2))
    uit = app.ingest_body(esp32.parse_data(hoger, dict(gps, alt_msl=35.0)))
    assert uit["agl_m"] == 10.0
    assert uit["fires"][0]["hotspot_lat"] is not None

    # 2D-fix (UBX fixType 2) heeft geen bruikbare hoogte: geen coördinaten.
    twee_d = dict(data, drone=dict(data["drone"], fix=2, alt_msl=35.0),
                  frame=_ander(data["frame"], 0.3))
    uit = app.ingest_body(
        esp32.parse_data(twee_d, dict(gps, fix=2, alt_msl=35.0)))
    assert uit["fires"][0]["hotspot_lat"] is None
    assert "fix" in uit["location_warning"]


def test_branddetectie_met_echte_sensorwaarden():
    # Realistische MLX90640-waarden: een veld op 27 C met een vlek van 95 C
    # over 2x2 cellen. Dat moet een brand zijn (>= 90 C en >= 45 C boven de
    # omgeving); een steen van 65 C hooguit verdacht.
    cfg = DEFAULT
    frame = [27.0] * 768
    for y in (10, 11):
        for x in (16, 17):
            frame[y * 32 + x] = 95.0
    ambient, threshold, hotspots = thermal.find_hotspots(frame, cfg)
    assert len(hotspots) == 1, "één vlek, één hotspot"
    assert hotspots[0]["max_temp"] == 95.0
    assert hotspots[0]["area"] == 4
    assert threshold > ambient
    oordeel = classify.classify_hotspot(hotspots[0], ambient, cfg)
    assert oordeel["level"] == "fire", oordeel
    assert oordeel["delta_t"] == 68.0
    steen = dict(hotspots[0], max_temp=65.0)
    assert classify.classify_hotspot(steen, ambient, cfg)["level"] == "suspect"


def test_vastgelopen_frame_bevestigt_geen_brand():
    # Een sensor die hetzelfde frame blijft herhalen mag nooit een brand
    # bevestigen — twee identieke beelden zijn geen twee metingen — en de
    # operator moet zien dat het beeld vastzit.
    app = server.App()
    drone = {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
             "heading_deg": 90.0, "fix": 3}
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.0)])
    app.ingest(list(frame), drone, 10.0)
    for _ in range(12):
        app.ingest(list(frame), drone, 10.0)
    staat = app.snapshot()
    assert staat["thermal"]["n_fires"] == 0, "identieke frames bevestigen niets"
    assert "vastgelopen" in (staat["warning"] or ""), staat["warning"]
    # Eén écht nieuwe meting (heter) bevestigt de brand wel.
    heter = list(frame)
    heter[8 * 32 + 20] += 5.0
    app.ingest(heter, drone, 10.0)
    staat = app.snapshot()
    assert staat["thermal"]["n_fires"] == 1, staat["thermal"]


def test_spiegel_frame_x():
    # Oriëntatie op één plek: kolom x wordt 31 - x, rijen blijven staan.
    assert esp32.spiegel_frame_x(list(range(6)), 3, 2) == [2, 1, 0, 5, 4, 3]
    frame = list(range(768))
    gespiegeld = esp32.spiegel_frame_x(frame)
    assert gespiegeld[0] == 31 and gespiegeld[31] == 0
    assert gespiegeld[32] == 63, "rij 1 begint weer links"
    assert esp32.spiegel_frame_x(gespiegeld) == frame, "twee keer = origineel"


def test_firmware_json_met_fix_geeft_coordinaten():
    # Precies zoals de ESP32 het stuurt zodra de GPS een positie heeft:
    # /api/data met frame + thermal + drone en /api/gps met dezelfde velden.
    app = server.App()
    frame = sim.make_frame(vlekken=[(4, 12, 260.0, 2.0)])  # links van midden
    drone = {"lat": 52.09, "lon": 4.31, "alt_msl": 45.0,
             "heading_deg": 0.0, "speed_mps": 0.0,
             "fix": 3, "sats": 12, "hdop": 0.8}
    data = {"frame": frame, "thermal_available": True,
            "thermal": {"min_c": 24.0, "max_c": 260.0, "fire": True,
                        "hotspot": {"x": 4, "y": 12}},
            "drone": dict(drone)}
    gps = dict(drone, data_seen=True, location_valid=True)

    # Eerste meting op lanceerhoogte: 45 m MSL wordt het lanceerpunt, dus
    # AGL 0 en nog geen coördinaten. Dat is correct gedrag, geen fout.
    uit = app.ingest_body(esp32.parse_data(data, gps))
    assert app._launch_alt == 45.0, "eerste 3D-fix zet het lanceerpunt"
    # Eén meting is nog geen bevestigde brand: verdacht, geen vuur.
    assert uit["n_suspects"] == 1 and uit["n_fires"] == 0, uit["fires"]
    assert uit["fires"][0]["hotspot_lat"] is None
    assert "AGL" in uit["location_warning"]

    # Klim naar 60 m MSL (AGL 15) met een nieuwe meting: nu wél coördinaten.
    hoger = dict(drone, alt_msl=60.0)
    frame2 = list(frame)
    frame2[12 * 32 + 4] += 1.0
    data2 = dict(data, frame=frame2, drone=hoger)
    uit2 = app.ingest_body(esp32.parse_data(data2, dict(gps, alt_msl=60.0)))
    assert uit2["n_fires"] == 1, "tweede meting bevestigt de brand"
    brand = uit2["fires"][0]
    assert brand["hotspot_lat"] is not None, uit2["location_warning"]
    assert abs(uit2["agl_m"] - 15.0) < 1e-6, uit2["agl_m"]
    # Pixel links van het midden bij heading 0 ligt westelijk van de drone.
    assert brand["hotspot_lon"] < 4.31, brand["hotspot_lon"]
    assert abs(brand["hotspot_lat"] - 52.09) < 1e-4
    assert 0.0 < brand["afstand_m"] < 25.0, brand["afstand_m"]

    # De staat toont de fix zoals het dashboard hem laat zien: UBX 3 -> 3D.
    snap = app.snapshot()
    assert snap["drone"]["fc_fix"] == 2, snap["drone"]
    assert snap["drone"]["fc_sats"] == 12


def test_hete_enkele_pixel_is_geen_ruis():
    # Op 30 m is één pixel ~2,6 x 1,9 m: een vlam die kleiner is levert één
    # cel van honderden graden. Die mag niet als ruis verdwijnen.
    frame = [27.0] * 768
    frame[10 * 32 + 16] = 250.0
    ambient, _thr, hotspots = thermal.find_hotspots(frame, DEFAULT)
    assert len(hotspots) == 1, "hete cel telt mee"
    assert hotspots[0]["area"] == 1
    oordeel = classify.classify_hotspot(hotspots[0], ambient, DEFAULT)
    assert oordeel["level"] == "fire", oordeel
    # Klein én lauw (dode pixel, reflectie): nog steeds geen hotspot.
    lauw = [27.0] * 768
    lauw[10 * 32 + 16] = 70.0
    _amb, _thr, geen = thermal.find_hotspots(lauw, DEFAULT)
    assert geen == [], geen


def test_autonomie_stub_is_uit():
    advies = autonomy.suggest_action(state.State())
    assert advies["enabled"] is False, "stub meldt zichzelf als uit"
    assert advies["action"] == "hold", "veilige default: hold"


def test_bevestiging_filtert_eenmalige_uitschieter():
    # Eén frame met een hete vlek is nog geen brand: pas als dezelfde plek
    # in twee opeenvolgende frames heet is, telt hij als bevestigd. Zo
    # verdwijnen losse sensorflarden uit het waarschuwingsbeeld.
    tracker = FireTracker()
    tracker.update([_brand()], now=0.0)
    _, events = tracker.update([], now=1.0)
    assert events == []
    uit, events = tracker.update([], now=3.0)
    assert [e["type"] for e in events] == ["lost"]
    assert uit[0]["confirmed"] is False


def test_onwaarschijnlijke_omgeving_geeft_geen_brand():
    # Log 30 okt: de sensor was niet op temperatuur (mediaan 486 C) en de
    # laptop meldde 137 branden in één vlucht. Zo'n frame is onbruikbaar:
    # waarschuwen, geen alarmering, en de hotspots blijven als diagnose.
    frame = [400.0] * 768
    frame[100] = 560.0
    r = pipeline.detect_event(frame, 52.09, 4.31, 90.0, 25.0, 10.0)
    assert r["sensor_warning"], "operator krijgt uitleg over de sensor"
    assert r["n_fires"] == 0, "geen branden uit een onbruikbaar frame"

    # Ook een vlek van brandformaat in een onbruikbaar frame (mediaan 80 C:
    # sensor niet op temperatuur) wordt niet als brand gemeld. De vlek
    # blijft wel als hotspot zichtbaar voor de diagnose.
    warm = [80.0] * 768
    for x, y in ((10, 10), (11, 10), (10, 11), (11, 11)):
        warm[y * DEFAULT.width + x] = 150.0
    r = pipeline.detect_event(warm, 52.09, 4.31, 90.0, 25.0, 10.0)
    assert r["sensor_warning"]
    assert r["n_fires"] == 0
    assert r["hotspots"], "de vlek blijft zichtbaar als diagnose"


def test_verdachte_track_telt_niet_als_brand():
    app = server.App()
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.5)])
    drone = {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
             "heading_deg": 90.0, "fix": 3}
    uit = app.ingest(frame, drone, 10.0)
    assert uit["fires"][0]["confirmed"] is False
    assert uit["n_fires"] == 0
    assert uit["n_suspects"] == 1
    assert app.snapshot()["thermal"]["n_fires"] == 0
    app.close()


def test_frame_sequentie_loopt_op():
    # De UI tekent alleen nieuwe frames en toont de leeftijd van het beeld.
    app = server.App()
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.5)])
    drone = {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
             "heading_deg": 90.0, "fix": 3}
    app.ingest(frame, drone, 10.0)
    app.ingest(frame, drone, 10.0)
    payload = app.frame_payload()
    assert payload["seq"] == 2
    assert payload["t"] is not None
    assert app.snapshot()["frame"]["seq"] == 2
    assert len(payload["cells"]) == 768
    app.close()


def test_identiek_frame_telt_niet_als_meting():
    # Een bevroren sensorread of een dubbel afgeleverd antwoord stuurt exact
    # dezelfde 768 waarden. Dat is geen tweede meting: een brand mag daar
    # niet door bevestigd worden.
    app = server.App()
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.5)])
    drone = {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0,
             "heading_deg": 90.0, "fix": 3}
    eerste = app.ingest(frame, drone, 10.0)
    tweede = app.ingest(list(frame), drone, 10.0)
    assert eerste["duplicate"] is False
    assert tweede["duplicate"] is True
    assert tweede["n_fires"] == 0, "identiek frame bevestigt niets"
    assert tweede["n_suspects"] == 1
    assert any("identiek frame" in regel for regel in app.state._logs)
    app.close()


def test_oude_positie_geeft_geen_coordinaten():
    # /api/gps valt weg terwijl het warmtebeeld doorkomt: de laatst bekende
    # positie mag geen coördinaten meer opleveren (die kloppen niet meer).
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.0)])
    r = pipeline.detect_event(frame, 52.09, 4.31, 90.0, 25.0, 10.0,
                              gps_fix=3, position_age_s=12.0)
    assert r["n_fires"] == 1, "de brand zelf wordt nog steeds gemeld"
    assert r["fires"][0]["hotspot_lat"] is None
    assert "oud" in r["location_warning"]

    # Verse positie: wel coördinaten.
    r = pipeline.detect_event(frame, 52.09, 4.31, 90.0, 25.0, 10.0,
                              gps_fix=3, position_age_s=0.4)
    assert r["fires"][0]["hotspot_lat"] is not None


def test_verse_drone_wint_van_oude_gps():
    # /api/data levert per frame een verse positie, /api/gps maar 1 Hz. De
    # verse moet winnen, anders rekent het dashboard met een oude positie.
    frame = sim.make_frame(vlekken=[(20, 8, 250.0, 2.5)])
    data = {"frame": frame,
            "drone": {"lat": 52.10, "lon": 4.32, "alt_msl": 30.0,
                      "heading_deg": 10.0, "fix": 3}}
    gps = {"lat": 52.09, "lon": 4.31, "alt_msl": 25.0}
    body = esp32.parse_data(data, gps)
    assert body["drone"]["lat"] == 52.10
    assert body["drone"]["alt_msl"] == 30.0
    # Zonder per-frame-drone vult /api/gps de positie.
    body = esp32.parse_data({"frame": frame}, gps)
    assert body["drone"]["lat"] == 52.09


def test_afgekapt_frame_is_geen_meting():
    # Een half antwoord mag geen ingest of een halve detectie worden: de
    # poll-lus vraagt het frame dan gewoon opnieuw.
    assert esp32.parse_data({"frame": [22.0] * 700}) is None
    assert esp32.parse_data({"frame": [22.0] * 768}) is not None


def test_lokale_sprong_detecteert_vlam_op_hoogte():
    # Velddata 11 nov 14:50: een echte brand stond 25 s lang op 45-66 C
    # (+38..+59 boven de omgeving) en werd pas "brand" toen de drone laag
    # genoeg hing. De ring naast de vlam is grond van 8 C: +47 C lokaal is
    # een vlam, ook al haalt hij de globale +60 C niet.
    oordeel = classify.classify_hotspot(
        {"max_temp": 55.0, "area": 5, "local_delta": 47.0,
         "core_contrast": 9.0}, 8.0)
    assert oordeel["is_fire"], oordeel
    assert oordeel["reasons"]["lokale_sprong"] is True
    assert oordeel["reasons"]["sprong_boven_omgeving"] is False


def test_steen_met_vlakke_kern_blijft_verdacht():
    # Zelfde absolute waarde en lokale sprong, maar een vlakke vlek: dat
    # is een zonverwarmde steen of dakpan, geen vlam.
    oordeel = classify.classify_hotspot(
        {"max_temp": 64.0, "area": 9, "local_delta": 48.0,
         "core_contrast": 2.0}, 20.0)
    assert not oordeel["is_fire"], oordeel
    assert oordeel["level"] == "suspect"


def test_verspreide_hete_cellen_worden_een_vlam():
    # Log 15:35: één vlam op hoogte kwam binnen als drie losse cellen
    # (328/185/79 C) met koude cellen ertussen. Die horen bij elkaar; als
    # losse blobs verdwenen ze elk na één frame en werden nooit bevestigd.
    frame = sim.make_frame(ambient=8.0, ruis=0.2)
    for x, y, temp in ((4, 7, 328.7), (6, 7, 79.3), (8, 7, 185.0)):
        frame[y * DEFAULT.width + x] = temp
    _, _, hotspots = thermal.find_hotspots(frame)
    assert len(hotspots) == 1, hotspots
    assert hotspots[0]["area"] >= 3


def test_groot_warm_vlak_is_geen_vlam():
    # Een dak of asfaltveld is zelf groot: de ring eromheen is net zo warm,
    # dus de lokale sprong is klein. De globale mediaan zou hier juist een
    # groot verschil zien.
    frame = [40.0] * (DEFAULT.width * DEFAULT.height)
    for y in range(8, 16):
        for x in range(8, 24):
            frame[y * DEFAULT.width + x] = 55.0
    _, _, hotspots = thermal.find_hotspots(frame)
    assert hotspots, "het warme vlak is heter dan de drempel"
    oordeel = classify.classify_hotspot(hotspots[0], 25.0)
    assert not oordeel["is_fire"], oordeel


def test_agl_referentie_negeert_gps_ruis():
    # Log 15:26: lanceerpunt 3.9 m MSL, daarna -2.5..6.3 m. De oude regel
    # maakte AGL 0..-6 m en every brand verloor zijn coördinaten.
    ref = geo.HeightReference()
    for alt in (3.9, -0.4, -2.5, -2.4, -2.5, -2.5, -2.5):
        agl = ref.update(alt)
        assert agl >= 0.0, "AGL mag nooit negatief worden"
    assert ref.ground == -2.5, ref.ground
    for _ in range(7):
        agl = ref.update(6.3)
    assert 8.0 <= agl <= 9.0, agl
    # Eén uitschieter naar beneden zet de grondreferentie niet op slot.
    ref.update(-20.0)
    assert ref.ground > -3.0, ref.ground


def test_vlam_op_hoogte_krijgt_coordinaten():
    # Kleine vlam (één cel) op 15 m AGL: moet brand zijn én coördinaten
    # krijgen. Dit is de combinatie die in de vlucht van 15:26 ontbrak.
    frame = sim.make_frame(ambient=8.0, vlekken=[(20, 8, 58.0, 1.2)])
    r = pipeline.detect_event(frame, 52.09, 4.31, 0.0, 20.0, 5.0)
    assert r["n_fires"] == 1, r["hotspots"]
    brand = r["fires"][0]
    assert brand["hotspot_lat"] is not None
    assert brand["local_delta"] >= 45.0


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main():
    for test in TESTS:
        test()
        print("ok - %s" % test.__name__)
    print("ALLE TESTS OK (%d)" % len(TESTS))


if __name__ == "__main__":
    main()
