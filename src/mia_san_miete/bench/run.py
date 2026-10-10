"""Benchmark suite. Every number in docs/benchmarks.md comes from this module.

Accuracy benchmarks run on the fictional corpora in `corpora/`; throughput benchmarks run on
synthetic listings through the real gate, score and draft code with fake routers.
"""

from __future__ import annotations

import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path

from ..config import Config
from ..db import Database
from ..dedup import is_same_flat
from ..demo import CITY, DISTRICTS, SOURCES, demo_config, demo_profile
from ..dispatcher import Dispatcher
from ..engine import Engine
from ..messaging.generator import DraftInvalid, generate_draft
from ..models import Listing
from ..profile import Profile
from ..providers.alert_email import AlertEmailProvider
from ..replies import CATEGORIES, IncomingMail, classify
from . import corpora

FIELDS = ["title", "warm", "cold", "area", "rooms", "postal"]
NOW = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


class _Box:
    def __init__(self, mail):
        self.mail = mail

    def fetch_recent(self, since):
        return [self.mail]


def _norm_title(t: str) -> str:
    return t.replace(",", ".").strip().lower()


def bench_parser() -> dict:
    mails = corpora.load("alerts")
    stats = {f: {"truth": 0, "pred": 0, "ok": 0} for f in FIELDS}
    found = spurious = total = 0
    by_style: dict[str, dict[str, int]] = {}
    misses: list[str] = []
    for m in mails:
        mail = IncomingMail("<x>", "Treffer", m["body"], "a@portal.test", [], NOW, {})
        got = {(lst.source, lst.source_id): lst
               for lst in AlertEmailProvider(_Box(mail), ["portal.test"], clock=lambda: NOW).fetch()}
        truth_keys = {(t["source"], t["source_id"]) for t in m["truth"]}
        spurious += len(set(got) - truth_keys)
        row = by_style.setdefault(m["style"], {"listings": 0, "all_ok": 0})
        for t in m["truth"]:
            total += 1
            row["listings"] += 1
            lst = got.get((t["source"], t["source_id"]))
            if lst is None:
                misses.append(f"style {m['style']}: listing not found")
                continue
            found += 1
            pred = {"title": lst.title, "warm": lst.warm_rent_eur, "cold": lst.cold_rent_eur,
                    "area": lst.area_m2, "rooms": lst.rooms, "postal": lst.postal_code}
            ok_all = True
            for f in FIELDS:
                tv, pv = t[f], pred[f]
                correct = (tv is not None and pv is not None
                           and (_norm_title(tv) == _norm_title(pv) if f == "title" else tv == pv))
                stats[f]["truth"] += tv is not None
                stats[f]["pred"] += pv is not None
                stats[f]["ok"] += correct
                if tv != pv and not (f == "title" and tv and pv and _norm_title(tv) == _norm_title(pv)):
                    ok_all = False
                    misses.append(f"style {m['style']} {f}: expected {tv!r}, got {pv!r}")
            row["all_ok"] += ok_all
    return {"mails": len(mails), "listings": total, "found": found, "spurious": spurious,
            "fields": stats, "by_style": by_style, "misses": misses[:12]}


def bench_classifier(corpus: str = "replies") -> dict:
    rows = corpora.load(corpus)
    matrix = {a: dict.fromkeys(CATEGORIES, 0) for a in CATEGORIES}
    errors = []
    for r in rows:
        pred = classify(r["subject"], r["body"], r["headers"])
        matrix[r["label"]][pred] += 1
        if pred != r["label"]:
            errors.append({"expected": r["label"], "got": pred, "text": r["body"][:70]})
    correct = sum(matrix[c][c] for c in CATEGORIES)
    per = {}
    for c in CATEGORIES:
        tp = matrix[c][c]
        fp = sum(matrix[o][c] for o in CATEGORIES if o != c)
        fn = sum(matrix[c][o] for o in CATEGORIES if o != c)
        per[c] = {"precision": tp / (tp + fp) if tp + fp else None,
                  "recall": tp / (tp + fn) if tp + fn else None, "n": tp + fn}
    committed = sum(matrix[a][b] for a in CATEGORIES for b in CATEGORIES if b != "other")
    committed_ok = sum(matrix[c][c] for c in CATEGORIES if c != "other")
    return {"n": len(rows), "accuracy": correct / len(rows), "matrix": matrix, "per_class": per,
            "errors": errors, "committed": committed, "committed_ok": committed_ok}


def bench_slots() -> dict:
    from ..scheduling import BERLIN, parse_slots
    received = datetime(2026, 11, 2, 10, 0, tzinfo=BERLIN)
    rows = corpora.load("slots_holdout")
    exact = false_slots = missed_slots = truth_total = 0
    misses = []
    for r in rows:
        got = {(s.start.month, s.start.day, s.start.hour, s.start.minute)
               for s in parse_slots(r["text"], received)}
        truth = {tuple(x) for x in r["slots"]}
        exact += got == truth
        false_slots += len(got - truth)
        missed_slots += len(truth - got)
        truth_total += len(truth)
        if got != truth:
            misses.append(f"\"{r['text'][:60]}\": got {sorted(got)}, expected {sorted(truth)}")
    return {"n": len(rows), "exact": exact, "false_slots": false_slots,
            "missed_slots": missed_slots, "truth_total": truth_total, "misses": misses}


def _listing(d: dict, source: str) -> Listing:
    return Listing(source=source, source_id=source, url="u", title="t", rooms=d["rooms"],
                   area_m2=d["area"], cold_rent_eur=d["cold"], warm_rent_eur=d.get("warm"),
                   postal_code=d["postal"], street=d["street"], seen_at=NOW)


def bench_dedup() -> dict:
    pairs = corpora.load("dedup")
    tp = fp = fn = tn = 0
    for p in pairs:
        pred = is_same_flat(_listing(p["a"], "a"), _listing(p["b"], "b"))
        if p["same"]:
            tp, fn = tp + pred, fn + (not pred)
        else:
            fp, tn = fp + pred, tn + (not pred)
    return {"pairs": len(pairs), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None}


class _FakeRouter:
    def __init__(self, mode):
        self.mode = mode

    def minutes(self, origin, destination, arrive_by):
        return 20.0


def _pool(n: int, seed: int = 3) -> list[Listing]:
    import random
    rng = random.Random(seed)
    out = []
    for i in range(n):
        rooms = rng.choice([1.5, 2, 2, 2.5, 3, 3.5])
        cold = round(rng.uniform(600, 1900) / 10) * 10
        out.append(Listing(
            source=SOURCES[i % len(SOURCES)], source_id=f"B-{i}", url="https://example.test/b",
            title=f"Helle {rooms:g}-Zimmer-Wohnung mit Balkon",
            description="Ruhige Lage, Einbauküche vorhanden, Balkon.",
            warm_rent_eur=cold + 250, cold_rent_eur=cold, area_m2=round(rooms * rng.uniform(22, 32), 1),
            rooms=rooms, street=f"Beispielweg {i}", postal_code=str(10000 + i), district=rng.choice(DISTRICTS),
            available_from=date(2027, 1, 15), landlord_type="private", seen_at=NOW,
            contact_email="vermieter@example.test"))
    return out


def _profile_cfg(tmp: Path) -> tuple[Config, Profile]:
    return Config.model_validate(demo_config(tmp, with_area=False)), Profile.model_validate(demo_profile())


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def bench_pipeline(n: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        cfg, profile = _profile_cfg(Path(tmp))
        pool = _pool(n)
        runs, lat = [], []
        for _ in range(3):
            db = Database()
            policy = cfg.send_policy.model_copy(update={"mode": "shadow"})
            eng = Engine(cfg.model_copy(update={"send_policy": policy}), profile,
                         Dispatcher(policy, db, {}), _FakeRouter("pt"), _FakeRouter("car"), None,
                         date(2026, 11, 1), lambda: NOW)
            lat = []
            t0 = time.perf_counter()
            for lst in pool:
                s0 = time.perf_counter()
                eng.process(lst, db.ingest(lst))
                lat.append((time.perf_counter() - s0) * 1000)
            runs.append(n / (time.perf_counter() - t0))
        return {"n": n, "runs": 3, "listings_per_s": statistics.median(runs),
                "p50_ms": _pct(lat, 0.5), "p95_ms": _pct(lat, 0.95)}


def bench_drafts(n: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        _, profile = _profile_cfg(Path(tmp))
        pool = _pool(n)
        invalid = 0
        t0 = time.perf_counter()
        for lst in pool:
            try:
                generate_draft(lst, profile, None, CITY)
            except DraftInvalid:
                invalid += 1
        dt = time.perf_counter() - t0
        return {"n": n, "invalid": invalid, "per_draft_ms": dt / n * 1000}


def run_all(quick: bool = False) -> dict:
    n = 200 if quick else 2000
    return {
        "parser": bench_parser(), "classifier": bench_classifier(), "holdout": bench_classifier("replies_holdout"),
        "dedup": bench_dedup(), "slots": bench_slots(),
        "pipeline": bench_pipeline(n), "drafts": bench_drafts(n),
        "env": {"date": datetime.now(UTC).strftime("%Y-%m-%d"), "python": sys.version.split()[0],
                "machine": f"{platform.system()} {platform.machine()}, {platform.processor() or 'cpu n/a'}",
                "commit": _commit(), "quick": quick},
    }


def _commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL, cwd=Path(__file__).parent).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _p(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def render_markdown(r: dict) -> str:
    e, pa, cl, dd, pl, dr = (r[k] for k in ("env", "parser", "classifier", "dedup", "pipeline", "drafts"))
    ho, sl = r["holdout"], r["slots"]
    out = [
        "# Benchmarks", "",
        f"Generated {e['date']} on top of commit `{e['commit']}` on {e['machine']}, Python {e['python']}"
        + (" (quick mode: smaller throughput sample)" if e["quick"] else "") + ".",
        "Reproduce with `mia bench --out docs/benchmarks.md`.", "",
        "## How to read these numbers", "",
        "- **Accuracy numbers (parser, classifier, dedup) are measured on fictional corpora that the",
        "  same author wrote as the heuristics.** They show that the code does what it was designed",
        "  to do and where it breaks on the cases we thought of. They are **not** estimates of",
        "  accuracy on real portal mail or real landlord replies. Real-data checks are tracked in",
        "  the repository issues.",
        "- Small samples: the reply corpus is a few dozen messages. One message is worth",
        "  several percentage points.",
        "- Throughput numbers are real measurements on the machine above, with fake routers (no",
        "  network) and no LLM. Real runs are dominated by routing and network latency, which is",
        "  not measured here.", "",
        f"## Alert-mail parser ({pa['mails']} mails, {pa['listings']} listings)", "",
        f"Listings found: {pa['found']}/{pa['listings']}; spurious listings: {pa['spurious']}.", "",
        "| Field | Recall | Precision | n (truth) |", "|---|---|---|---|",
    ]
    for f in FIELDS:
        s = pa["fields"][f]
        out.append(f"| {f} | {_p(s['ok'] / s['truth'] if s['truth'] else None)} | "
                   f"{_p(s['ok'] / s['pred'] if s['pred'] else None)} | {s['truth']} |")
    out += ["", "All fields correct, by mail style:", "", "| Style | Listings | All correct |", "|---|---|---|"]
    for k, v in sorted(pa["by_style"].items()):
        out.append(f"| {k} | {v['listings']} | {_p(v['all_ok'] / v['listings'])} |")
    if pa["misses"]:
        out += ["", "Examples of misses (these are real parser bugs or format gaps):", ""]
        out += [f"- {m}" for m in pa["misses"]]
    out += ["", f"## Reply classifier, tuning set ({cl['n']} messages)", "",
            "The keyword lists were adjusted after a first run on this set, so a high score here "
            "mostly shows the fitting worked. Use it as a regression test, not as an accuracy "
            "estimate.", "",
            f"Overall accuracy: {_p(cl['accuracy'])}.", "",
            "| Category | Precision | Recall | n |", "|---|---|---|---|"]
    for c, s in cl["per_class"].items():
        out.append(f"| {c} | {_p(s['precision'])} | {_p(s['recall'])} | {s['n']} |")
    if cl["errors"]:
        out += ["", "Misclassified:", ""]
        out += [f"- expected `{x['expected']}`, got `{x['got']}`: \"{x['text']}\"" for x in cl["errors"]]
    out += ["", f"## Reply classifier, held-out set ({ho['n']} messages)", "",
            "Written after the latest rewrite (the two earlier held-out sets became tuning data once "
            "their misses were used) and never tuned against: the more honest number, though "
            "still small, fictional and written by the same author.", "",
            f"Overall accuracy: {_p(ho['accuracy'])}. When the classifier commits to a category "
            f"other than `other`, it was right {ho['committed_ok']} of {ho['committed']} times: "
            "it misses more than it mislabels, and unrecognized replies land in `other` (shown "
            "as \"Needs a look\" in the dashboard).", "",
            "| Category | Precision | Recall | n |", "|---|---|---|---|"]
    for c, s_ in ho["per_class"].items():
        out.append(f"| {c} | {_p(s_['precision'])} | {_p(s_['recall'])} | {s_['n']} |")
    if ho["errors"]:
        out += ["", "Misclassified (known gaps, not fixed on purpose):", ""]
        out += [f"- expected `{x['expected']}`, got `{x['got']}`: \"{x['text']}\"" for x in ho["errors"]]
    out += ["", f"## Viewing-slot extraction ({sl['n']} messages, deterministic parser)", "",
            "Written after the parser and never tuned against. What matters for automatic "
            "replies is the safety line: a slot that was *not* offered must never be accepted.", "",
            f"- Exactly right: {sl['exact']}/{sl['n']} messages.",
            f"- Slots offered but not found: {sl['missed_slots']}/{sl['truth_total']} "
            "(safe: the reply goes to the review queue).",
            f"- Slots found that were not offered: {sl['false_slots']} (the number that must stay 0).",
            ""]
    out += [f"- Miss: {m}" for m in sl["misses"]]
    out += ["", f"## Duplicate detection ({dd['pairs']} pairs, half same flat, half hard negatives)", "",
            f"Precision {_p(dd['precision'])}, recall {_p(dd['recall'])} "
            f"(TP {dd['tp']}, FP {dd['fp']}, FN {dd['fn']}, TN {dd['tn']}).",
            "False negatives are expected by design: sparse listings are never merged on weak "
            "evidence, which prefers a duplicate notification over silently hiding a flat.", "",
            f"## Pipeline throughput ({pl['n']} listings, median of {pl['runs']} runs)", "",
            "Ingest, dedup, gates, score, template draft and audit write, fake routers, in-memory "
            "database, shadow mode.", "",
            f"- {pl['listings_per_s']:.0f} listings/s; per-listing p50 {pl['p50_ms']:.2f} ms, "
            f"p95 {pl['p95_ms']:.2f} ms.", "",
            f"## Template drafts ({dr['n']} listings)", "",
            f"- Invalid drafts: {dr['invalid']}/{dr['n']}; {dr['per_draft_ms']:.2f} ms per draft.",
            "- LLM opening acceptance rate: not measured (needs an LLM endpoint).", "",
            "## Not measured here", "",
            "- Router latency and cache hit rate (needs a network and a real router).",
            "- Anything on real portal mail, real replies or real listings.", ""]
    return "\n".join(out)


def main(out: str | None, as_json: bool, quick: bool) -> int:
    r = run_all(quick)
    if as_json:
        print(json.dumps(r, indent=1, default=str))
        return 0
    md = render_markdown(r)
    if out:
        Path(out).write_text(md, encoding="utf-8")
        print(f"written {out}")
    else:
        print(md)
    return 0
