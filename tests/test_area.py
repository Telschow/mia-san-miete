import json
from datetime import UTC, datetime

import pytest

from mia_san_miete.config import Area, Criteria, Station
from mia_san_miete.db import Database
from mia_san_miete.gates import GateResult, check_area, evaluate_gates
from mia_san_miete.geo.area import (
    AreaResult,
    CachedGeo,
    SafeGeo,
    Stop,
    compute_area,
    haversine_km,
    needs_geo,
    stop_kinds,
    walking_minutes,
)
from mia_san_miete.geo.motis import MotisRouter
from mia_san_miete.models import Listing
from mia_san_miete.scoring import station_component
from tests.test_p2 import CFG

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
CENTER = (48.1400, 11.5600)


def crit(**kw) -> Criteria:
    return CFG.criteria.model_copy(update=kw)


def lst(**kw) -> Listing:
    base = {"source": "x", "source_id": "1", "url": "u", "title": "t", "street": "Weg 1",
            "postal_code": "80331", "district": "Altstadt", "seen_at": NOW}
    base.update(kw)
    return Listing(**base)


class FakeGeo:
    """Places any address at a point derived from a table; stops from a list."""

    def __init__(self, points=None, stops=None):
        self.points = {"Hauptbahnhof": CENTER, **(points or {})}
        self.stops, self.calls = stops or [], []

    def geocode(self, text):
        self.calls.append(("geo", text))
        for key, pt in self.points.items():
            if key in text:
                return pt
        return None

    def nearest_stops(self, lat, lon, radius_m):
        self.calls.append(("stops", radius_m))
        return list(self.stops)


def test_distance_and_walk_math():
    assert haversine_km((50.0, 8.0), (50.0, 8.0)) == 0
    assert haversine_km((0.0, 0.0), (1.0, 0.0)) == pytest.approx(111.19, abs=0.05)
    assert walking_minutes(0.5, 4.8, 1.3) == pytest.approx(8.125)
    assert stop_kinds(("SUBWAY", "bus")) == {"subway", "bus"}
    assert stop_kinds(()) == set()


def test_config_rules():
    assert Area(center="Hbf", max_km=5).max_km == 5
    with pytest.raises(ValueError, match="needs area.center"):
        Area(max_km=5)
    assert Station().kinds == ["subway", "rail", "tram"] and Station().required is False
    assert not needs_geo(CFG.criteria)
    assert needs_geo(crit(area=Area(center="Hbf", max_km=5)))
    assert needs_geo(crit(station=Station(max_walk_minutes=10)))


def test_compute_area_radius_and_nearest_matching_stop():
    c = crit(area=Area(center="Hauptbahnhof", max_km=10),
             station=Station(max_walk_minutes=10, kinds=["subway", "rail"]))
    flat = (48.1500, 11.5600)                                    # about 1.1 km north of the center
    stops = [Stop("Bus Platz", 48.1501, 11.5600, ("BUS",)),      # nearest, but not a counted kind
             Stop("Marktplatz", 48.1540, 11.5600, ("SUBWAY",)),  # about 450 m
             Stop("Fernbahnhof", 48.1700, 11.5600, ("RAIL",)),
             Stop("Haltestelle", 48.1502, 11.5600, ())]          # modes unknown: counts, nearest
    geo = FakeGeo({"Weg 1": flat}, stops)
    a = compute_area(lst(), c, geo, "Teststadt")
    assert a.located and a.km == pytest.approx(1.11, abs=0.02)
    assert a.station == "Haltestelle" and a.stop_found is True        # unknown modes are not excluded
    assert a.walk_minutes == pytest.approx(walking_minutes(0.022, 4.8, 1.3), abs=0.2)
    geo2 = FakeGeo({"Weg 1": flat}, stops[:3])
    b = compute_area(lst(), c, geo2, "Teststadt")
    assert (b.station, b.station_kind) == ("Marktplatz", "subway")


def test_compute_area_unknowns_and_estimates():
    c = crit(area=Area(center="Hauptbahnhof", max_km=10))
    assert compute_area(lst(), c, None, "X") is None                    # no geo service
    assert compute_area(lst(), CFG.criteria, FakeGeo(), "X") is None    # nothing configured
    unplaced = compute_area(lst(), c, FakeGeo(), "X")                   # address not found
    assert unplaced.located is False and unplaced.km is None
    coarse = compute_area(lst(street=None), c, FakeGeo({"80331": (48.15, 11.56)}), "X")
    assert coarse.estimated is True and coarse.km is not None
    none_found = compute_area(lst(), crit(station=Station(max_walk_minutes=8)),
                              FakeGeo({"Weg 1": (48.15, 11.56)}, []), "X")
    assert none_found.stop_found is False and none_found.walk_minutes is None


def gate(criteria, listing=None, area=None) -> GateResult:
    out = GateResult()
    check_area(listing or lst(), criteria, area, out)
    return out


def test_postal_and_district_lists_need_no_network():
    c = crit(area=Area(include_postal_codes=["803", "804"], exclude_districts=["Gewerbe"]))
    assert gate(c).rejects == [] and gate(c).reviews == []
    assert "outside your list" in gate(c, lst(postal_code="10115")).rejects[0]
    assert "unknown" in gate(c, lst(postal_code=None)).reviews[0]
    assert "excluded" in gate(c, lst(district="Gewerbegebiet Nord")).rejects[0]
    assert "excluded" in gate(crit(area=Area(exclude_postal_codes=["80331"]))).rejects[0]


def test_radius_gate_rejects_far_reviews_unknown_and_borderline():
    c = crit(area=Area(center="Hbf", max_km=5))
    ok = gate(c, area=AreaResult(True, False, km=3.0))
    assert not ok.rejects and not ok.reviews and not ok.flags
    assert "limit 5" in gate(c, area=AreaResult(True, False, km=8.0)).rejects[0]
    assert gate(c, area=AreaResult(True, True, km=5.3)).reviews           # estimated and close: review
    assert gate(c, area=AreaResult(True, True, km=7.0)).rejects
    assert gate(c, area=None).reviews and gate(c, area=AreaResult(False)).reviews   # unknown: review
    assert gate(c, area=AreaResult(True, True, km=3.0)).flags


def test_station_limit_is_optional_and_never_rejects_on_missing_data():
    s_soft = crit(station=Station(max_walk_minutes=10, required=False))
    assert gate(s_soft, area=AreaResult(True, False, walk_minutes=40.0)).rejects == []
    s = crit(station=Station(max_walk_minutes=10, required=True))
    far = gate(s, area=AreaResult(True, False, walk_minutes=15.0, station="Marktplatz"))
    assert "Marktplatz" in far.rejects[0]
    assert gate(s, area=AreaResult(True, True, walk_minutes=12.0)).reviews    # borderline, estimated
    assert gate(s, area=AreaResult(True, False, walk_minutes=None, stop_found=False)).reviews
    assert gate(s, area=None).reviews
    assert gate(s, area=AreaResult(True, False, walk_minutes=6.0)).rejects == []


def test_station_score_component_and_weight_gate():
    c = crit(station=Station(max_walk_minutes=10))
    assert station_component(AreaResult(True, walk_minutes=4.0), c) == 1.0
    assert station_component(AreaResult(True, walk_minutes=20.0), c) == 0.0
    assert 0 < station_component(AreaResult(True, walk_minutes=12.0), c) < 1
    assert station_component(None, c) == 0.3 and station_component(AreaResult(True), c) == 0.3
    from mia_san_miete.scoring import score_listing
    flat = lst(warm_rent_eur=1400, area_m2=60, rooms=2)
    base = score_listing(flat, c, CFG.commute, None, CFG.scoring, NOW)
    assert "station" not in base.breakdown                              # weight 0: no effect
    weighted = CFG.scoring.model_copy(update={"weights": CFG.scoring.weights.model_copy(
        update={"station": 10})})
    res = score_listing(flat, c, CFG.commute, None, weighted, NOW, AreaResult(True, walk_minutes=3.0))
    assert res.breakdown["station"]["value"] == 1.0


def test_evaluate_gates_runs_area_checks():
    c = crit(area=Area(exclude_postal_codes=["80331"]))
    g = evaluate_gates(lst(warm_rent_eur=1400, area_m2=60, rooms=2), c, CFG.commute, None)
    assert any("excluded" in r for r in g.rejects)


def test_cache_and_safety_wrappers():
    db = Database()
    inner = FakeGeo({"Weg 1": (48.15, 11.56)}, [Stop("A", 48.151, 11.56, ("SUBWAY",))])
    geo = CachedGeo(inner, db)
    assert geo.geocode("Weg 1") == (48.15, 11.56) and geo.geocode("weg 1") == (48.15, 11.56)
    assert sum(1 for c in inner.calls if c[0] == "geo") == 1             # second call from cache
    assert geo.geocode("Nowhere 9") is None and geo.geocode("Nowhere 9") is None
    assert sum(1 for c in inner.calls if c == ("geo", "Nowhere 9")) == 2  # failures not cached
    assert geo.nearest_stops(48.15, 11.56, 800)[0].name == "A"
    geo.nearest_stops(48.15, 11.56, 800)
    assert sum(1 for c in inner.calls if c[0] == "stops") == 1

    class Boom:
        def geocode(self, text):
            raise OSError("down")

        def nearest_stops(self, *a):
            raise OSError("down")

    safe = SafeGeo(Boom())
    assert safe.geocode("x") is None and safe.nearest_stops(1, 2, 3) == []


def test_motis_geocode_and_stop_parsing_is_defensive():
    def get(url):
        if "/geocode" in url:
            return [{"lat": 48.14, "lon": 11.56}]
        return [{"name": "Near", "lat": 48.1405, "lon": 11.56, "modes": ["SUBWAY"]},
                {"name": "Far", "lat": 48.2, "lon": 11.56, "modes": ["BUS"]},       # beyond radius
                {"lat": "x"}, "junk", {"name": "NoModes", "lat": 48.1402, "lon": 11.56}]

    r = MotisRouter("https://m.example.test", get)
    assert r.geocode("anything") == (48.14, 11.56)
    stops = r.nearest_stops(48.14, 11.56, 1000)
    assert [s.name for s in stops] == ["Near", "NoModes"] and stops[0].modes == ("SUBWAY",)
    assert MotisRouter(get=lambda url: []).geocode("x") is None


def test_engine_stores_area_and_rejects_flats_outside_the_limit(tmp_path, profile):
    from tests.test_p4 import Recorder, _engine, _go, _l
    db = Database()
    eng, _ = _engine(tmp_path, profile, db, Recorder(), enabled=False)
    c = eng.config.criteria.model_copy(update={"area": Area(center="Hauptbahnhof", max_km=2)})
    eng.config = eng.config.model_copy(update={"criteria": c})
    eng.geo = FakeGeo({"Leopoldstraße": (48.20, 11.56)})              # about 6.7 km away
    assert _go(eng, db, _l()).status == "skipped"
    row = db.conn.execute("SELECT commute, reasons FROM actions").fetchone()
    assert json.loads(row["commute"])["area"]["km"] > 6 and "from the center" in row["reasons"]


def test_dashboard_view_carries_area_with_limits_and_no_places():
    from mia_san_miete.gui.api import commute_view
    cfg_crit = CFG.criteria.model_copy(update={"area": Area(center="Hauptbahnhof, Teststadt", max_km=8),
                                               "station": Station(max_walk_minutes=10, required=True)})
    cfg = CFG.model_copy(update={"criteria": cfg_crit})
    raw = json.dumps({"times": {"work_a": {"pt": 20.0, "car": None}}, "estimated": False,
                      "area": {"located": True, "estimated": True, "km": 5.2, "walk_minutes": 7.5,
                               "station": "Marktplatz", "station_kind": "subway", "stop_found": True}})
    view = commute_view(raw, cfg)
    assert view["area"]["max_km"] == 8 and view["area"]["max_walk"] == 10 and view["area"]["walk_required"]
    assert view["area"]["station"] == "Marktplatz" and view["area"]["km"] == 5.2
    assert "Hauptbahnhof" not in json.dumps(view)                 # the center's address stays out
    assert commute_view(json.dumps({"times": {}, "estimated": False, "area": None}), cfg)["area"] is None
