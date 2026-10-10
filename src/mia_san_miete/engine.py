"""Per-flat processing: commute, gates, score, decision, draft, dispatch."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

from .config import Config
from .db import IngestResult
from .decision import Decision, current_threshold, decide
from .dispatcher import Dispatcher, Outcome
from .gates import evaluate_gates
from .geo.area import Geo, compute_area
from .geo.travel import Router, compute_commute
from .messaging.generator import Draft, DraftInvalid, generate_draft
from .messaging.llm import OpeningWriter
from .models import Listing
from .profile import Profile
from .scoring import score_listing


class Engine:
    def __init__(
        self,
        config: Config,
        profile: Profile,
        dispatcher: Dispatcher,
        pt: Router,
        car: Router,
        writer: OpeningWriter | None,
        live_since: date,
        clock: Callable[[], datetime],
        geo: Geo | None = None,
    ) -> None:
        self.config, self.profile, self.dispatcher = config, profile, dispatcher
        self.pt, self.car, self.writer = pt, car, writer
        self.live_since, self.clock = live_since, clock
        self.geo = geo

    def process(self, listing: Listing, ingest: IngestResult) -> Outcome:
        now = self.clock()
        cfg = self.config
        commute = compute_commute(listing, cfg.commute, self.pt, self.car, now, cfg.city.name)
        area = compute_area(listing, cfg.criteria, self.geo, cfg.city.name)
        gates = evaluate_gates(listing, cfg.criteria, cfg.commute, commute, area)
        score = score_listing(listing, cfg.criteria, cfg.commute, commute, cfg.scoring, now, area)
        threshold = current_threshold(cfg.send_policy, self.live_since, now.date())
        decision = decide(gates, score.score, cfg.send_policy, threshold, listing.source)
        reasons = gates.rejects + gates.reviews + gates.flags

        draft: Draft | None = None
        if decision is not Decision.SKIP:
            try:
                draft = generate_draft(listing, self.profile, self.writer, cfg.city.name)
            except DraftInvalid as exc:
                decision = Decision.NEEDS_APPROVAL   # never auto-send an invalid draft
                reasons.append(f"draft invalid: {exc}")
        return self.dispatcher.handle(
            listing=listing,
            canonical_id=ingest.canonical_id,
            decision=decision,
            score=score,
            reasons=reasons,
            draft=draft,
            now=now,
            commute=commute,
            area=area,
        )
