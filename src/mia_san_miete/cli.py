"""Command line entry point (`mia`)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from . import __version__
from .config import load_config
from .config_docs import render as render_config_docs
from .config_docs import write_all as write_config_docs
from .db import Database
from .demo import build_demo_dispatcher, build_demo_responder, seed, write_demo_files
from .gui.server import App, serve, settings_editable
from .health import Health
from .messaging.generator import DraftInvalid, generate_draft
from .metrics import compute_metrics, format_metrics
from .net import RedirectProbe, explain
from .pipeline import run_once
from .presets import UnknownPreset, list_presets, preset_answers
from .privacy import HOOK, scan_history, scan_repo
from .profile import load_profile
from .providers.alert_email import AlertEmailProvider, ClickResolver
from .providers.base import FixtureProvider
from .queue import ApprovalQueue, QueueError
from .replies import ImapMailbox, check_replies
from .report import shadow_report
from .runner import build_dispatcher, build_engine, build_notifier, build_reply_tools, run_cycle
from .wizard import Prompter, WizardError, build, collect, install_hook, write_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mia", description="Mia san Miete")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check-config", help="validate a config file")
    check.add_argument("path", nargs="?", default="config.yaml")

    ing = sub.add_parser("ingest-fixture", help="dry run: ingest listings from a JSON file")
    ing.add_argument("path")
    ing.add_argument("--db", default=":memory:")

    prev = sub.add_parser("draft-preview", help="print template drafts for a listings JSON file")
    prev.add_argument("path")
    prev.add_argument("--profile", default="profile/profile.yaml")
    prev.add_argument("--city", default="")

    for name, text in (("kill", "stop all sending now"), ("resume", "lift the kill switch")):
        k = sub.add_parser(name, help=text)
        k.add_argument("--config", default="config.yaml")

    rep = sub.add_parser("check-replies", help="scan the inbox for replies to sent messages")
    rep.add_argument("--config", default="config.yaml")
    rep.add_argument("--profile", default="profile/profile.yaml")

    run = sub.add_parser("run", help="one cycle: read alerts, score, draft, dispatch per policy")
    run.add_argument("--config", default="config.yaml")
    run.add_argument("--profile", default="profile/profile.yaml")

    ini = sub.add_parser("init", help="guided setup: writes your private config files")
    ini.add_argument("--dir", default=".", help="project folder (default: current)")
    ini.add_argument("--env-file", default="~/.config/mia/env", help="where the secrets file goes")
    ini.add_argument("--answers", default=None, help="YAML file of answers (no questions asked)")
    ini.add_argument("--force", action="store_true", help="overwrite, keeping .bak copies")
    ini.add_argument("--city", default=None, help="preset city (see `mia presets`)")
    ini.add_argument("--household", default=None, help="preset household (see `mia presets`)")
    ini.add_argument("--no-hook", action="store_true", help="do not offer the git pre-commit hook")

    pre = sub.add_parser("presets", help="list the city and household presets")
    pre.add_argument("--lang", choices=["de", "en"], default="de")

    dcf = sub.add_parser("docs-config", help="print or write the generated configuration reference")
    dcf.add_argument("--lang", choices=["de", "en"], default="de")
    dcf.add_argument("--write", action="store_true", help="write both languages and the JSON schema")
    dcf.add_argument("--out", default="docs")

    gui = sub.add_parser("gui", help="local web dashboard")
    gui.add_argument("--config", default="config.yaml")
    gui.add_argument("--profile", default="profile/profile.yaml")
    gui.add_argument("--env-file", default="~/.config/mia/env",
                     help="where saved credentials are kept (default: ~/.config/mia/env)")
    gui.add_argument("--host", default="127.0.0.1")
    gui.add_argument("--port", type=int, default=8765)
    gui.add_argument("--allow-remote-settings", action="store_true",
                     help="allow editing settings and passwords over a non-local address "
                          "(plain HTTP: only behind an SSH tunnel or VPN)")
    gui.add_argument("--allow-host", action="append", default=[],
                     help="extra Host header value to accept (when serving beyond localhost)")

    dem = sub.add_parser("demo", help="dashboard on fictional data (nothing real, nothing sent)")
    dem.add_argument("--dir", default=None, help="where to put the demo files (default: temp)")
    dem.add_argument("--port", type=int, default=8765)

    bench = sub.add_parser("bench", help="run the benchmark suite (fictional corpora)")
    bench.add_argument("--out", default=None, help="write markdown here, e.g. docs/benchmarks.md")
    bench.add_argument("--json", action="store_true")
    bench.add_argument("--quick", action="store_true", help="smaller throughput sample")

    que = sub.add_parser("queue", help="review drafts waiting for approval")
    que.add_argument("action", choices=["list", "show", "approve", "skip", "sent"])
    que.add_argument("action_id", nargs="?", type=int)
    que.add_argument("--config", default="config.yaml")
    que.add_argument("--profile", default="profile/profile.yaml")

    rpt = sub.add_parser("shadow-report", help="what the agent decided, to review a shadow run")
    rpt.add_argument("--config", default="config.yaml")
    rpt.add_argument("--days", type=int, default=14)
    rpt.add_argument("--limit", type=int, default=15)

    rtr = sub.add_parser("check-router", help="probe the public-transport router live")
    rtr.add_argument("--config", default="config.yaml")
    rtr.add_argument("--origin", required=True, help='e.g. "Marienplatz, München"')

    car = sub.add_parser("check-area", help="probe the radius and nearest-stop lookups live")
    car.add_argument("--config", default="config.yaml")
    car.add_argument("--origin", required=True, help='an address, e.g. "Beispielweg 1, 80331 München"')

    alr = sub.add_parser("ingest-alerts", help="read portal alert emails and store new flats")
    alr.add_argument("--config", default="config.yaml")
    alr.add_argument("--show-mail", metavar="DOMAIN", default=None,
                     help="print an outline of up to 2 mails from this sender domain (no "
                          "addresses or greetings; check it before sharing)")
    alr.add_argument("--link-shapes", action="store_true",
                     help="print the masked link structure of the alert mails (safe to share)")

    met = sub.add_parser("metrics", help="funnel and reply statistics")
    met.add_argument("--config", default="config.yaml")
    met.add_argument("--days", type=int, default=None, help="only the last N days")

    mkt = sub.add_parser("market-rent", help="median warm rent per m2 of the flats seen so far")
    mkt.add_argument("--config", default="config.yaml")

    priv = sub.add_parser("check-private", help="scan tracked files for private data")
    priv.add_argument("--root", default=".")
    priv.add_argument("--terms", default=None, help="terms file (default: <root>/.private-terms)")

    hist = sub.add_parser("check-history", help="scan the whole git history for private data")
    hist.add_argument("--root", default=".")
    hist.add_argument("--terms", default=None, help="terms file (default: <root>/.private-terms)")

    hook = sub.add_parser("install-hook", help="install a git pre-commit hook running the scan")
    hook.add_argument("--root", default=".")

    args = parser.parse_args(argv)

    if args.command == "check-config":
        try:
            cfg = load_config(args.path)
        except (OSError, ValidationError, ValueError) as exc:
            print(f"config invalid: {exc}", file=sys.stderr)
            return 1
        policy = cfg.send_policy
        print(f"config ok (send_policy: enabled={policy.enabled}, mode={policy.mode})")
        return 0
    if args.command == "ingest-fixture":
        db = Database(args.db)
        stats = run_once([FixtureProvider(args.path)], db, notifier=None)
        print(
            f"fetched={stats.fetched} new_flats={stats.new_flats} "
            f"duplicates={stats.duplicates} failed={stats.failed_providers}"
        )
        return 1 if stats.failed_providers else 0
    if args.command == "draft-preview":
        try:
            profile = load_profile(args.profile)
        except (OSError, ValidationError, ValueError) as exc:
            print(f"profile invalid: {exc}", file=sys.stderr)
            return 1
        for listing in FixtureProvider(args.path).fetch():
            tag = f"[{listing.source}/{listing.source_id}]"
            try:
                draft = generate_draft(listing, profile, writer=None, city=args.city)
            except DraftInvalid as exc:
                print(f"{tag} draft invalid: {exc}\n")
                continue
            print(f"{tag} {draft.subject}\n\n{draft.body}\n")
        return 0
    if args.command in ("kill", "resume"):
        try:
            flag = load_config(args.config).send_policy.kill_switch_file
        except (OSError, ValidationError, ValueError) as exc:
            print(f"config invalid: {exc}", file=sys.stderr)
            return 1
        if args.command == "kill":
            flag.touch()
            print(f"kill switch ON ({flag})")
        else:
            flag.unlink(missing_ok=True)
            print("kill switch off")
        return 0
    if args.command == "run":
        try:
            cfg = load_config(args.config)
            profile = load_profile(args.profile)
        except (OSError, ValidationError, ValueError) as exc:
            print(f"config or profile invalid: {exc}", file=sys.stderr)
            return 1
        if cfg.alerts is None:
            print("config has no `alerts` section", file=sys.stderr)
            return 1
        a = cfg.alerts
        user, password = os.environ.get(a.username_env), os.environ.get(a.password_env)
        if not user or not password:
            print("IMAP credentials missing in the environment", file=sys.stderr)
            return 1
        db = Database(cfg.storage.db_path)
        engine = build_engine(cfg, profile, db, os.environ)
        resolver = ClickResolver(RedirectProbe(), db.kv_get, db.kv_set)
        provider = AlertEmailProvider(
            ImapMailbox(a.imap_host, a.imap_port, user, password, a.folder),
            a.sender_domains, a.lookback_days, resolver=resolver,
        )
        notifier = build_notifier(cfg, os.environ)
        health = Health(db, notifier, cfg.notifications.heartbeat_hours,
                        cfg.notifications.silence_alert_hours)
        try:
            stats = run_cycle(engine, db, [provider], notifier)
        except Exception as exc:
            health.failure(f"cycle crashed: {type(exc).__name__}")
            raise
        health.after_cycle(stats)
        ApprovalQueue(db, engine.dispatcher, profile).purge()
        pol = cfg.send_policy
        print(
            f"fetched={stats.fetched} new_flats={stats.new_flats} "
            f"duplicates={stats.duplicates} failed={stats.failed_providers} "
            f"(send_policy enabled={pol.enabled} mode={pol.mode})"
        )
        return 1 if stats.failed_providers else 0
    if args.command == "init":
        import yaml as _yaml
        prompter = Prompter()
        try:
            preset = preset_answers(args.city, args.household)
            if args.answers:
                answers = {**preset, **(_yaml.safe_load(Path(args.answers).read_text(encoding="utf-8")) or {})}
            else:
                answers = collect(prompter, preset)
            built = build(answers)
            written = write_files(Path(args.dir), built, Path(args.env_file), args.force)
        except (WizardError, UnknownPreset, OSError, _yaml.YAMLError) as exc:
            print(f"init stopped: {exc}", file=sys.stderr)
            return 1
        print("\nWritten (all gitignored, none will be committed):")
        for path, how in written:
            print(f"  {path}  ({how})")
        if not args.no_hook and (Path(args.dir) / ".git").exists():
            if args.answers or prompter.yes("Install the pre-commit hook that blocks private data?"):
                print(f"  git hook: {install_hook(Path(args.dir))}")
        print('''
Starting state: sending disabled, shadow mode on. Nothing leaves your machine.

Next:
  1. Put the mail passwords in the env file (names are listed there, values are empty).
  2. mia check-config config.yaml
  3. mia draft-preview tests/fixtures/listings.json --profile profile/profile.yaml
  4. Follow docs/how-to.md from part 4 (alert inbox) and part 5 (check on real data).''')
        return 0
    if args.command == "presets":
        info = list_presets(args.lang)
        print("Städte" if args.lang == "de" else "Cities")
        for c in info["cities"]:
            print(f"  {c['key']:<12} {c['label']}  ({c['station']})")
        print("Haushalte" if args.lang == "de" else "Households")
        for h in info["households"]:
            print(f"  {h['key']:<12} {h['label']}: {h['description']}")
        print("\nmia init --city <key> --household <key>")
        return 0
    if args.command == "docs-config":
        if args.write:
            for path in write_config_docs(Path(args.out)):
                print(f"written {path}")
        else:
            print(render_config_docs(args.lang))
        return 0
    if args.command == "bench":
        from .bench.run import main as bench_main
        return bench_main(args.out, args.json, args.quick)
    if args.command == "gui":
        from .gui.loader import make_loader
        from .gui.settings import SettingsStore
        store = SettingsStore(Path(args.config), Path(args.profile), Path(args.env_file))
        loader = make_loader(Path(args.config), Path(args.profile), store)
        if store.exists():
            try:
                cfg, db, queue = loader()
            except (OSError, ValidationError, ValueError) as exc:
                print(f"config invalid: {exc}\nFix it in the file, or move it away to run the "
                      "first-run setup in the browser.", file=sys.stderr)
                return 1
            if queue is None:
                print("profile not loaded: queue actions disabled until it is fixed in Settings",
                      file=sys.stderr)
        else:
            cfg = db = queue = None
            print("No configuration found: the dashboard opens a first-run setup.")
        editable = settings_editable(args.host, args.allow_remote_settings)
        if not editable:
            print("Settings are read-only on a non-local address (they take passwords over plain "
                  "HTTP). Edit on localhost, or add --allow-remote-settings behind a tunnel or VPN.")
            if cfg is None:
                print("No configuration exists yet: run `mia gui` on localhost once to set up.",
                      file=sys.stderr)
                return 1
        serve(App(cfg, db, queue, store=store if editable else None, loader=loader), args.host,
              args.port, args.allow_host)
        return 0
    if args.command == "demo":
        directory = Path(args.dir) if args.dir else Path(tempfile.mkdtemp(prefix="mia-demo-"))
        cfg_path, prof_path = write_demo_files(directory)
        cfg, profile = load_config(cfg_path), load_profile(prof_path)
        db = Database(cfg.storage.db_path, check_same_thread=False)
        if db.kv_get("demo") != "1":
            seed(db, cfg, profile, datetime.now(UTC))
        print(f"DEMO MODE: fictional data in {directory}; nothing is sent anywhere.")
        queue = ApprovalQueue(db, build_demo_dispatcher(cfg, db), profile,
                              build_demo_responder(cfg, db, profile))
        serve(App(cfg, db, queue, demo=True), "127.0.0.1", args.port)
        return 0
    if args.command == "queue":
        try:
            cfg = load_config(args.config)
            profile = load_profile(args.profile)
        except (OSError, ValidationError, ValueError) as exc:
            print(f"config or profile invalid: {exc}", file=sys.stderr)
            return 1
        db = Database(cfg.storage.db_path)
        _, responder = build_reply_tools(cfg, profile, db, os.environ, None)
        queue = ApprovalQueue(db, build_dispatcher(cfg, db, os.environ), profile, responder)
        try:
            if args.action == "list":
                for it in queue.items():
                    lst = it["listing"] or {}
                    score = "n/a" if it["score"] is None else f"{it['score']:.0f}"
                    tag = "reply " if it["kind"] == "reply" else ""
                    print(f"{it['action_id']:>5}  {tag}score {score:>3}  {it['source']:<14} "
                          f"{lst.get('title', '')[:50]}  [{'; '.join(it['reasons'])[:60]}]")
                return 0
            if args.action_id is None:
                print("action_id required", file=sys.stderr)
                return 2
            if args.action == "show":
                it = next((i for i in queue.items() if i["action_id"] == args.action_id), None)
                if it is None:
                    print("no pending draft with that id", file=sys.stderr)
                    return 1
                print(f"{it['subject']}\n\n{it['body']}")
                return 0
            if args.action == "approve":
                out = queue.approve(args.action_id)
                print(f"result: {out.status}")
                return 0 if out.status == "sent" else 1
            if args.action == "sent":
                queue.mark_sent(args.action_id)
                print("recorded as sent by you")
                return 0
            queue.skip(args.action_id)
            print("skipped")
            return 0
        except QueueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.command == "shadow-report":
        try:
            cfg = load_config(args.config)
        except (OSError, ValidationError, ValueError) as exc:
            print(f"config invalid: {exc}", file=sys.stderr)
            return 1
        print(shadow_report(Database(cfg.storage.db_path), args.days, datetime.now(UTC),
                            args.limit))
        return 0
    if args.command == "check-area":
        try:
            cfg = load_config(args.config)
        except (OSError, ValidationError, ValueError) as exc:
            print(f"config invalid: {exc}", file=sys.stderr)
            return 1
        from .geo.area import haversine_km, stop_kinds, walking_minutes
        from .geo.motis import make_pt_router
        geo = make_pt_router(cfg.commute.pt_router, cfg.commute.motis_base_url)
        crit = cfg.criteria
        try:
            point = geo.geocode(args.origin)
            print(f"origin: {'not found' if point is None else f'{point[0]:.5f}, {point[1]:.5f}'}")
            if point and crit.area and crit.area.center:
                center = geo.geocode(crit.area.center)
                if center:
                    km = haversine_km(point, center)
                    print(f"distance to center: {km:.1f} km (limit {crit.area.max_km or 'none'})")
            if point and crit.station and crit.station.max_walk_minutes:
                s = crit.station
                stops = geo.nearest_stops(point[0], point[1], 3000)
                print(f"stops found within 3 km: {len(stops)} (modes may be missing: "
                      f"{sum(1 for x in stops if not x.modes)} without)")
                for stop in sorted(stops, key=lambda x: haversine_km(point, (x.lat, x.lon)))[:5]:
                    d = haversine_km(point, (stop.lat, stop.lon))
                    print(f"  {stop.name}: {d * 1000:.0f} m, about "
                          f"{walking_minutes(d, s.walking_speed_kmh, s.detour_factor):.0f} min walk, "
                          f"kinds {sorted(stop_kinds(stop.modes)) or 'unknown'}")
            if not (crit.area and crit.area.center) and not (
                    crit.station and crit.station.max_walk_minutes):
                print("Nothing else to check: set criteria.area.center (+ max_km) and/or "
                      "criteria.station.max_walk_minutes in the config to test those lookups.")
            print("Compare with a map by hand: this lookup is unverified.")
        except Exception as exc:  # noqa: BLE001 - report any network or API error
            print(f"lookup error {explain(exc)}")
            return 1
        return 0
    if args.command == "check-router":
        try:
            cfg = load_config(args.config)
        except (OSError, ValidationError, ValueError) as exc:
            print(f"config invalid: {exc}", file=sys.stderr)
            return 1
        from .geo.motis import make_pt_router
        from .geo.travel import next_weekday_arrival
        router = make_pt_router(cfg.commute.pt_router, cfg.commute.motis_base_url)
        failed = False
        for t in cfg.commute.targets:
            arrive = next_weekday_arrival(datetime.now(UTC), t.arrival_time)
            try:
                minutes = router.minutes(args.origin, t.destination, arrive)
            except Exception as exc:  # noqa: BLE001 - report any network or API error
                print(f"{t.name}: router error {explain(exc)}")
                failed = True
                continue
            print(f"{t.name}: {'no route found' if minutes is None else f'{minutes:.0f} min'} "
                  f"(arrive {arrive:%a %H:%M}); compare by hand with a journey planner")
            failed = failed or minutes is None
        return 1 if failed else 0
    if args.command == "market-rent":
        try:
            cfg = load_config(args.config)
        except (OSError, ValidationError, ValueError) as exc:
            print(f"config invalid: {exc}", file=sys.stderr)
            return 1
        import json
        import statistics
        seen: dict[object, float] = {}
        for cid, raw in Database(cfg.storage.db_path).conn.execute(
                "SELECT canonical_id, data FROM listings"):
            item = json.loads(raw)
            warm = item.get("warm_rent_eur") or (item.get("cold_rent_eur") or 0) * 1.2
            if warm and item.get("area_m2"):
                seen[cid] = warm / item["area_m2"]
        if len(seen) < 10:
            print(f"only {len(seen)} flats with rent and size so far; collect at least 10 more first")
            return 1
        v = sorted(seen.values())
        q1, med, q3 = statistics.quantiles(v, n=4)[0], statistics.median(v), statistics.quantiles(v, n=4)[2]
        print(f"{len(v)} distinct flats: median {med:.1f} EUR/m2 warm (middle half {q1:.1f} to {q3:.1f})")
        print(f"to use it: criteria.market_warm_rent_per_m2: {med:.0f}")
        print("note: this is the median of what your alerts showed, not of the whole market")
        return 0
    if args.command == "ingest-alerts":
        try:
            cfg = load_config(args.config)
        except (OSError, ValidationError, ValueError) as exc:
            print(f"config invalid: {exc}", file=sys.stderr)
            return 1
        if cfg.alerts is None:
            print("config has no `alerts` section", file=sys.stderr)
            return 1
        a = cfg.alerts
        user, password = os.environ.get(a.username_env), os.environ.get(a.password_env)
        if not user or not password:
            print("IMAP credentials missing in the environment", file=sys.stderr)
            return 1
        db = Database(cfg.storage.db_path)
        resolver = ClickResolver(RedirectProbe(), db.kv_get, db.kv_set)
        provider = AlertEmailProvider(
            ImapMailbox(a.imap_host, a.imap_port, user, password, a.folder),
            a.sender_domains, a.lookback_days, resolver=resolver,
        )
        stats = run_once([provider], db, notifier=None)
        if resolver.requests or resolver.skipped_over_cap:
            print(f"click links looked up: {resolver.requests} "
                  f"(over the per-run limit, left for next run: {resolver.skipped_over_cap})")
            for shape, n in resolver.dead_ends.most_common(5):
                print(f"  {n} x lookup did not end at a flat: {shape}")
        print(
            f"fetched={stats.fetched} new_flats={stats.new_flats} "
            f"duplicates={stats.duplicates} failed={stats.failed_providers}"
        )
        if args.show_mail:
            from .providers.alert_email import mail_skeleton
            shown = 0
            for dom, mails in provider.samples.items():
                if dom == args.show_mail or dom.endswith("." + args.show_mail):
                    for mail in mails:
                        shown += 1
                        print(f"\n===== mail {shown} from {dom} =====")
                        print(mail_skeleton(mail))
            if not shown:
                print(f"no mail from {args.show_mail} in the last {a.lookback_days} days")
        if args.link_shapes:
            print("link shapes in mails from your sender_domains (host/path, ids masked):")
            for shape, n in provider.link_shapes.most_common(25):
                print(f"  {n:3d} x {shape}")
        if stats.fetched == 0:
            print(
                f"mailbox '{a.folder}', last {a.lookback_days} days: {provider.mails_seen} mails, "
                f"{provider.mails_allowed} from your sender_domains, "
                f"{provider.mails_without_links} of those without a recognised flat link"
            )
            if provider.skipped_domains:
                top = ", ".join(f"{d} ({n})" for d, n in provider.skipped_domains.most_common(8))
                print(f"ignored sender domains: {top}")
                print("add the portal's domain to alerts.sender_domains if it is among them")
        return 1 if stats.failed_providers else 0
    if args.command in ("check-replies", "metrics"):
        try:
            cfg = load_config(args.config)
        except (OSError, ValidationError, ValueError) as exc:
            print(f"config invalid: {exc}", file=sys.stderr)
            return 1
        db = Database(cfg.storage.db_path)
        if args.command == "metrics":
            since = None
            if args.days:
                since = (datetime.now(UTC) - timedelta(days=args.days)).isoformat(
                    timespec="seconds")
            print(format_metrics(compute_metrics(db, since)))
            return 0
        if cfg.replies is None:
            print("config has no `replies` section", file=sys.stderr)
            return 1
        user = os.environ.get(cfg.replies.username_env)
        password = os.environ.get(cfg.replies.password_env)
        if not user or not password:
            print("IMAP credentials missing in the environment", file=sys.stderr)
            return 1
        mailbox = ImapMailbox(cfg.replies.imap_host, cfg.replies.imap_port, user, password,
                              cfg.replies.folder)
        try:
            profile = load_profile(args.profile)
        except (OSError, ValidationError, ValueError):
            profile = None
        llm, responder = build_reply_tools(cfg, profile, db, os.environ,
                                           build_notifier(cfg, os.environ))
        try:
            stats, _ = check_replies(db, mailbox, datetime.now(UTC), cfg.replies.lookback_days,
                                     llm, responder)
        except OSError as exc:
            print(f"imap failure: {type(exc).__name__}", file=sys.stderr)
            return 1
        print(f"scanned={stats.scanned} matched={stats.matched} unmatched={stats.unmatched} "
              f"categories={stats.by_category}")
        return 0
    if args.command == "check-private":
        findings = scan_repo(args.root, args.terms)
        for f in findings:
            print(f"{f.path}:{f.line}: {f.kind}", file=sys.stderr)
        if findings:
            print(f"{len(findings)} private-data finding(s); commit blocked", file=sys.stderr)
            return 1
        print("no private data found")
        return 0
    if args.command == "check-history":
        try:
            report = scan_history(args.root, args.terms)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f"history scan failed: {type(exc).__name__}", file=sys.stderr)
            return 1
        print(f"scanned {report.commits} commits, {report.blobs} file versions, {report.refs} refs")
        if report.shallow:
            print("WARNING: shallow clone, older history is missing. Run `git fetch --unshallow`.",
                  file=sys.stderr)
        for b in report.binaries:
            print(f"binary file in history (look at it by hand): {b}")
        for f in report.findings:
            print(f"{f.commit} {f.where} {f.path}:{f.line}: {f.kind}", file=sys.stderr)
        if report.findings:
            print(f"{len(report.findings)} finding(s) in the history", file=sys.stderr)
            return 1
        if report.shallow:
            return 1
        print("no private data found in the history")
        return 0
    if args.command == "install-hook":
        hook_path = Path(args.root) / ".git" / "hooks" / "pre-commit"
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        hook_path.write_text(HOOK.format(python=sys.executable), encoding="utf-8")
        hook_path.chmod(0o755)
        print(f"hook installed at {hook_path}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
