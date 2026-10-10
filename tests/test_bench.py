import json

from mia_san_miete.bench import corpora
from mia_san_miete.bench.run import (
    bench_classifier,
    bench_dedup,
    bench_drafts,
    bench_parser,
    bench_pipeline,
    render_markdown,
    run_all,
)


def test_committed_corpora_match_the_generators():
    """Corpora are generated, never hand-edited: a drift means someone forgot to regenerate."""
    for name, fresh in (("replies", corpora.reply_corpus()), ("replies_holdout", corpora.holdout_corpus()),
                        ("alerts", corpora.alert_corpus()), ("slots_holdout", corpora.slot_corpus()), ("dedup", corpora.dedup_corpus())):
        assert corpora.load(name) == json.loads(json.dumps(fresh, ensure_ascii=False)), name


def test_corpora_are_fictional():
    text = json.dumps([corpora.load(n) for n in ("replies", "replies_holdout", "alerts", "dedup")])
    assert "@" not in text.replace("@portal.test", "")


def test_parser_regression_gate():
    r = bench_parser()
    assert r["found"] == r["listings"] and r["spurious"] == 0
    assert all(v["all_ok"] == v["listings"] for v in r["by_style"].values()), r["misses"]


def test_classifier_tuning_set_regression_gate():
    assert bench_classifier()["accuracy"] == 1.0


def test_classifier_holdout_floor():
    """Not a target: the floor below is the value measured on the held-out set (0.57).
    Raise it when the classifier genuinely improves; never lower it to make CI pass."""
    assert bench_classifier("replies_holdout")["accuracy"] >= 0.55


def test_slot_parser_never_invents_slots():
    from mia_san_miete.bench.run import bench_slots
    r = bench_slots()
    assert r["false_slots"] == 0, r["misses"]       # safety invariant
    assert r["exact"] >= 11                         # measured 12/15 on the frozen set


def test_dedup_floors():
    r = bench_dedup()
    assert r["precision"] >= 0.95 and r["recall"] >= 0.85


def test_throughput_and_drafts_run():
    assert bench_pipeline(30)["listings_per_s"] > 0
    assert bench_drafts(30)["invalid"] == 0


def test_report_renders_with_all_sections():
    md = render_markdown(run_all(quick=True))
    for heading in ("Alert-mail parser", "tuning set", "held-out set", "Duplicate detection",
                    "Pipeline throughput", "Not measured here"):
        assert heading in md
