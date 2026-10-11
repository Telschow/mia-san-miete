from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from mia_san_miete.config import load_config
from mia_san_miete.db import Database
from mia_san_miete.decision import Decision, current_threshold, decide
from mia_san_miete.gates import GateResult, Verdict, evaluate_gates, mentions
from mia_san_miete.geo.travel import (
    BERLIN,
    CachedRouter,
    CommuteResult,
    GoogleRoutesRouter,
    compute_commute,
    next_weekday_arrival,
    origin_for,
)
from mia_san_miete.models import Listing
from mia_san_miete.scoring import score_listing

CFG = load_config(Path(__file__).resolve().parent.parent / "config.example.yaml")
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)   # a Monday


def CR(a_pt, b_car, b_pt, estimated):
    return CommuteResult(
        {"work_a": {"pt": a_pt, "car": None}, "work_b": {"pt": b_pt, "car": b_car}}, estimated
    )


GOOD = CR(18, 22, 35, False)


def _l(**kw) -> Listing:
    base = {
        "source": "immoscout", "source_id": "1", "url": "u", "title": "2 Zimmer Schwabing",
        "warm_rent_eur": 1450, "cold_rent_eur": 1200, "area_m2": 60, "rooms": 2,
        "street": "Leopoldstraße", "postal_code": "80802",
        "available_from": date(2027, 1, 15), "landlord_type": "private", "seen_at": NOW,
    }
    base.update(kw)
    return Listing(**base)


def _gate(listing, commute=GOOD) -> GateResult:
    return evaluate_gates(listing, CFG.criteria, CFG.commute, commute)


def test_clean_listing_passes():
    assert _gate(_l()).verdict is Verdict.PASS


def test_price_and_size_rejects():
    r = _gate(_l(warm_rent_eur=1800))
    assert r.verdict is Verdict.REJECT
    assert _gate(_l(area_m2=50)).verdict is Verdict.REJECT
    assert _gate(_l(rooms=1)).verdict is Verdict.REJECT


def test_missing_rent_is_review_and_single_rent_is_flagged():
    assert _gate(_l(warm_rent_eur=None, cold_rent_eur=None)).verdict is Verdict.REVIEW
    r = _gate(_l(warm_rent_eur=None, cold_rent_eur=1200))
    assert r.verdict is Verdict.PASS and "warm rent estimated" in r.flags
    assert _gate(_l(warm_rent_eur=None, cold_rent_eur=1450)).verdict is Verdict.REJECT


def test_wbs_rejected_but_negation_is_not():
    assert _gate(_l(description="WBS erforderlich")).verdict is Verdict.REJECT
    assert _gate(_l(description="Kein WBS erforderlich")).verdict is Verdict.PASS
    assert mentions("ohne WBS", "WBS") is False
    assert mentions("Tauschwohnung", "Tausch") is False   # whole word only


def test_zwischenmiete_furnished_and_scam_reject():
    assert _gate(_l(title="Zwischenmiete 3 Monate")).verdict is Verdict.REJECT
    assert _gate(_l(description="voll möbliert")).verdict is Verdict.REJECT
    assert _gate(_l(description="vollmöbliert")).verdict is Verdict.REJECT
    assert _gate(_l(description="Tauschwohnung")).verdict is Verdict.REJECT
    assert _gate(_l(description="unmöbliert")).verdict is Verdict.PASS
    assert _gate(_l(description="teilmöbliert")).verdict is Verdict.PASS
    assert _gate(_l(description="nicht möbliert")).verdict is Verdict.PASS
    assert _gate(_l(description="Fully furnished flat")).verdict is Verdict.REJECT
    assert _gate(_l(description="Unfurnished flat")).verdict is Verdict.PASS
    assert _gate(_l(description="Zahlung per Western Union")).verdict is Verdict.REJECT
    assert _gate(_l(deposit_eur=4000)).verdict is Verdict.REJECT
    assert _gate(_l(description="befristet")).verdict is Verdict.REVIEW


def test_move_in_rules():
    assert _gate(_l(available_from=date(2027, 2, 1))).verdict is Verdict.PASS
    assert _gate(_l(available_from=date(2027, 3, 1))).verdict is Verdict.REJECT
    dec = _gate(_l(available_from=date(2026, 12, 15)))
    assert dec.verdict is Verdict.PASS and any("negotiable" in f for f in dec.flags)
    assert _gate(_l(available_from=date(2026, 11, 1))).verdict is Verdict.REJECT
    assert _gate(_l(available_from=None)).verdict is Verdict.REVIEW
    imm = _gate(_l(available_from=None, available_immediately=True))
    assert imm.verdict is Verdict.PASS and imm.flags


def test_commute_rule_or_branch_and_borderline():
    assert _gate(_l(), CR(18, 40, 35, False)).verdict is Verdict.PASS   # pt ok
    assert _gate(_l(), CR(18, 22, 55, False)).verdict is Verdict.PASS   # car ok
    assert _gate(_l(), CR(18, 40, 55, False)).verdict is Verdict.REJECT
    assert _gate(_l(), CR(33, 22, 35, False)).verdict is Verdict.REJECT
    # estimated and within the 5 minute margin: review, not reject
    assert _gate(_l(), CR(33, 22, 35, True)).verdict is Verdict.REVIEW
    assert _gate(_l(), CR(40, 22, 35, True)).verdict is Verdict.REJECT
    assert _gate(_l(), None).verdict is Verdict.REVIEW


def test_score_is_deterministic_and_explained():
    a = score_listing(_l(), CFG.criteria, CFG.commute, GOOD, CFG.scoring, NOW)
    b = score_listing(_l(), CFG.criteria, CFG.commute, GOOD, CFG.scoring, NOW)
    assert a == b and 0 <= a.score <= 100
    assert set(a.breakdown) >= {"commute", "price", "freshness"}
    better = score_listing(
        _l(title="2 Zimmer mit Südbalkon und Tiefgaragenstellplatz"), CFG.criteria, CFG.commute, GOOD,
        CFG.scoring, NOW,
    )
    assert better.score > a.score
    stale = score_listing(
        _l(published_at=NOW - timedelta(hours=20)), CFG.criteria, CFG.commute, GOOD,
        CFG.scoring, NOW,
    )
    assert stale.score < a.score


def test_threshold_schedule_and_decision():
    p = CFG.send_policy
    start = date(2026, 11, 1)
    assert current_threshold(p, start, start) == 85
    assert current_threshold(p, start, start + timedelta(days=6)) == 75
    assert current_threshold(p, start, start + timedelta(days=300)) == 70   # floor
    live = p.model_copy(update={"enabled": True, "platform_allow_list": ["immoscout"]})
    ok = GateResult()
    assert decide(ok, 90, live, 85, "immoscout") is Decision.AUTO_SEND
    assert decide(ok, 80, live, 85, "immoscout") is Decision.NEEDS_APPROVAL
    assert decide(ok, 99, live, 85, "kleinanzeigen") is Decision.NEEDS_APPROVAL
    assert decide(ok, 99, p, 85, "immoscout") is Decision.NEEDS_APPROVAL   # disabled
    assert decide(GateResult(reviews=["x"]), 99, live, 70, "immoscout") is Decision.NEEDS_APPROVAL
    assert decide(GateResult(rejects=["x"]), 99, live, 0, "immoscout") is Decision.SKIP


class FakeRouter:
    def __init__(self, mode, value):
        self.mode, self.value, self.calls, self.arrivals = mode, value, 0, []

    def minutes(self, origin, destination, arrive_by):
        self.calls += 1
        self.arrivals.append((destination, f"{arrive_by.astimezone(BERLIN):%H:%M}"))
        return self.value


def test_commute_is_computed_cached_and_estimated_flag_set():
    db = Database()
    pt, car = FakeRouter("pt", 20.0), FakeRouter("car", 25.0)
    cpt, ccar = CachedRouter(pt, db), CachedRouter(car, db)
    full = compute_commute(_l(), CFG.commute, cpt, ccar, NOW, "München")
    assert full.estimated is False and full.times["work_b"]["car"] == 25.0
    compute_commute(_l(source_id="2"), CFG.commute, cpt, ccar, NOW, "München")
    assert pt.calls == 2 and car.calls == 1   # work_a is pt-only; cached by address          # second flat, same address: cached
    vague = compute_commute(_l(street=None), CFG.commute, cpt, ccar, NOW, "München")
    assert vague.estimated is True
    none = compute_commute(_l(street=None, postal_code=None), CFG.commute, cpt, ccar, NOW, "München")
    assert none == CommuteResult({}, True)
    assert origin_for(_l(street=None, postal_code=None, district="Schwabing"), "Hamburg") == ("Schwabing, Hamburg", True)


def test_arrival_times_are_per_destination():
    pt, car = FakeRouter("pt", 20.0), FakeRouter("car", 25.0)
    compute_commute(_l(), CFG.commute, pt, car, NOW, "München")
    a, b = CFG.commute.targets
    assert (a.destination, "09:00") in pt.arrivals
    assert (b.destination, "08:30") in pt.arrivals
    assert car.arrivals == [(b.destination, "08:30")]   # only work_b limits car travel


def test_next_weekday_arrival_skips_weekend():
    sat = datetime(2026, 11, 7, 12, 0, tzinfo=BERLIN)
    nxt = next_weekday_arrival(sat, "08:30")
    assert nxt.weekday() == 0 and (nxt.hour, nxt.minute) == (8, 30)


def test_google_router_parses_duration_and_handles_empty():
    seen = {}

    def post(url, headers, body):
        seen.update(headers=headers, body=body)
        return {"routes": [{"duration": "1500s"}]}

    r = GoogleRoutesRouter("KEY", post=post)
    assert r.minutes("a", "b", NOW) == 25.0
    assert seen["headers"]["X-Goog-Api-Key"] == "KEY"
    assert seen["body"]["travelMode"] == "DRIVE"
    assert GoogleRoutesRouter("K", post=lambda *a: {}).minutes("a", "b", NOW) is None


def test_threshold_never_exceeds_min_score():
    p = CFG.send_policy.model_copy(update={"min_score": 50})   # floor 70 > min_score
    assert current_threshold(p, date(2026, 11, 1), date(2026, 11, 1)) == 50


def _cfg_with(**commute_overrides):
    return CFG.commute.model_copy(update=commute_overrides)


def test_combine_any_and_all_modes_are_configurable():
    a, b = CFG.commute.targets
    only_a_ok = CR(18, 40, 55, False)       # work_a passes, work_b fails
    out = GateResult()
    from mia_san_miete.gates import check_commute

    check_commute(only_a_ok, _cfg_with(combine="any"), out)
    assert out.verdict is Verdict.PASS
    out = GateResult()
    check_commute(only_a_ok, _cfg_with(combine="all"), out)
    assert out.verdict is Verdict.REJECT
    strict_b = b.model_copy(update={"modes": "all"})
    out = GateResult()
    check_commute(CR(18, 22, 55, False), _cfg_with(targets=[a, strict_b]), out)
    assert out.verdict is Verdict.REJECT    # car ok but pt too long, and both are required


def test_unknown_time_goes_to_review_not_reject():
    out = GateResult()
    from mia_san_miete.gates import check_commute

    check_commute(CR(18, None, None, False), CFG.commute, out)
    assert out.verdict is Verdict.REVIEW


def test_city_is_configurable_for_routing():
    pt, car = FakeRouter("pt", 20.0), FakeRouter("car", 25.0)
    seen = []
    pt.minutes = lambda o, d, a: seen.append(o) or 20.0
    compute_commute(_l(street="Reeperbahn 1", postal_code="20359"), CFG.commute, pt, car, NOW,
                    "Hamburg")
    assert seen and all(o.endswith("20359 Hamburg") for o in seen)


def test_rent_per_m2_and_weak_scam_signals():
    from mia_san_miete.gates import GateResult, check_rent_per_m2, check_scam

    c = CFG.criteria.model_copy(update={"max_warm_rent_per_m2": 30, "market_warm_rent_per_m2": 24})

    def rent(warm, area):
        out = GateResult()
        check_rent_per_m2(_l(warm_rent_eur=warm, area_m2=area), c, out)
        return out

    assert rent(1800, 50).rejects                                 # 36 EUR/m2 above the hard limit
    assert rent(500, 50).reviews                                  # 10 EUR/m2 is under half the market
    assert rent(900, 60).flags and not rent(900, 60).reviews      # 15 EUR/m2 is well below
    assert rent(1400, 60).verdict == Verdict.PASS                 # 23.3 EUR/m2 is normal

    def scam(text):
        out = GateResult()
        check_scam(_l(description=text), out)
        return out

    assert scam("Zahlung per Paysafe").rejects
    assert scam("Schlüssel wird per DHL verschickt").rejects
    assert scam("Vermieter im Ausland, Kontakt nur per WhatsApp").reviews
    one = scam("Kontakt nur über WhatsApp")
    assert one.flags and not one.reviews and not one.rejects


def test_motis_car_router_reads_direct_leg_and_rush_hour_factor_scales():
    from mia_san_miete.geo.motis import MotisCarRouter
    from mia_san_miete.geo.travel import ScaledRouter

    seen = []

    def fake_get(url):
        seen.append(url)
        if "geocode" in url:
            return [{"lat": 48.1, "lon": 11.5}]
        return {"direct": [{"duration": 1200}], "itineraries": []}

    car = MotisCarRouter("https://motis.example.test", get=fake_get)
    arrive = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
    assert car.minutes("A", "B", arrive) == 20.0
    assert any("directModes=CAR" in u and "transitModes=" in u for u in seen)
    assert ScaledRouter(car, 1.3).minutes("A", "B", arrive) == 26.0


def test_unknown_move_in_can_be_a_flag_and_empty_alerts_are_skipped():
    crit = CFG.criteria
    flagged = crit.model_copy(update={"move_in": crit.move_in.model_copy(update={"unknown": "flag"})})
    full = dict(warm_rent_eur=1200, area_m2=60, rooms=2, available_from=None)
    assert any("move-in date unknown" in r for r in evaluate_gates(
        _l(**full), crit, CFG.commute, GOOD).reviews)
    g = evaluate_gates(_l(**full), flagged, CFG.commute, GOOD)
    assert not any("move-in" in r for r in g.reviews) and "move-in date unknown" in g.flags
    empty = evaluate_gates(_l(warm_rent_eur=None, cold_rent_eur=None, area_m2=None, rooms=None),
                           crit, CFG.commute, GOOD)
    assert any("no details" in r for r in empty.rejects)
