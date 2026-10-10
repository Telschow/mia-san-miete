"""Viewing slots: read offered times from a reply, fit them to your availability, write the
answer. Deterministic; an LLM may only suggest slots, which are checked here like any other.

Everything is Europe/Berlin local time. Rules, not guesses: a time without "Uhr", a colon or
am/pm is not a time, and a weekday without a time is not a slot.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .profile import Availability

BERLIN = ZoneInfo("Europe/Berlin")
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_NAMES = {
    "montag": 0, "monday": 0, "dienstag": 1, "tuesday": 1, "mittwoch": 2, "wednesday": 2,
    "donnerstag": 3, "thursday": 3, "freitag": 4, "friday": 4, "samstag": 5, "saturday": 5,
    "sonnabend": 5, "sonntag": 6, "sunday": 6,
}
MONTHS = {
    "januar": 1, "january": 1, "februar": 2, "february": 2, "märz": 3, "march": 3, "april": 4,
    "mai": 5, "may": 5, "juni": 6, "june": 6, "juli": 7, "july": 7, "august": 8,
    "september": 9, "oktober": 10, "october": 10, "november": 11, "dezember": 12,
    "december": 12,
}
DE_DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
EN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MAX_SLOT_CANDIDATES = 6

_DAY = "|".join(sorted(DAY_NAMES, key=len, reverse=True))
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
_TOKEN = re.compile(
    rf"(?P<rel>übermorgen|morgen|heute|tomorrow|today)"
    rf"|(?P<day>\b(?:{_DAY})\b)"
    rf"|(?P<dmy>\b\d{{1,2}}\.\s?\d{{1,2}}\.(?:\s?\d{{2,4}})?)"
    rf"|(?P<dm>\b\d{{1,2}}\.?\s+(?:{_MONTH})\b(?:\s+\d{{4}})?)"
    rf"|(?P<md>\b(?:{_MONTH})\s+\d{{1,2}}(?:st|nd|rd|th)?\b)"
    rf"|(?P<range>\b(?:zwischen|between|von|from)?\s*(?P<r1>\d{{1,2}})(?:[:.](?P<r1m>\d{{2}}))?"
    rf"\s*(?:uhr|am|pm)?\s*(?:-|–|bis|und|to|and)\s*(?P<r2>\d{{1,2}})(?:[:.](?P<r2m>\d{{2}}))?"
    rf"\s*(?P<ru>uhr|am|pm)\b)"
    rf"|(?P<time>\b(?P<h>\d{{1,2}})(?:[:.](?P<m>\d{{2}}))?\s*(?P<u>uhr|am|pm)\b"
    rf"|\b(?P<h2>\d{{1,2}}):(?P<m2>\d{{2}})\b)",
    re.IGNORECASE)


def strip_for_llm(text: str) -> str:
    """Text that may leave the process: quotes removed (they hold our own message), no
    addresses, links or phone-like numbers."""
    from .replies import strip_quotes  # local import: replies imports this module's users
    text = strip_quotes(text)
    text = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[email]", text)
    text = re.sub(r"https?://\S+", "[link]", text)
    text = re.sub(r"(?<!\d)(?:\+|00)?\d[\d /-]{8,}\d", "[number]", text)
    return text


@dataclass(frozen=True)
class Slot:
    start: datetime                # earliest arrival offered
    end: datetime | None = None    # latest the landlord is available (a range), if stated


def _hour(h: int, unit: str | None, minute: int = 0) -> tuple[int, int] | None:
    unit = (unit or "").lower()
    if unit == "pm" and h < 12:
        h += 12
    elif unit == "am" and h == 12:
        h = 0
    return (h, minute) if 0 <= h < 24 and 0 <= minute < 60 else None


def _parse_date(token: re.Match[str], received: datetime) -> date | None:
    text = token.group(0).lower()
    today = received.astimezone(BERLIN).date()
    try:
        if token.group("rel"):
            return today + timedelta(days={"heute": 0, "today": 0, "morgen": 1, "tomorrow": 1,
                                            "übermorgen": 2}[text])
        if token.group("day"):
            ahead = (DAY_NAMES[text] - today.weekday()) % 7 or 7
            return today + timedelta(days=ahead)
        year = None
        if token.group("dmy"):
            parts = [int(x) for x in re.findall(r"\d+", text)]
            day, month = parts[0], parts[1]
            year = parts[2] + (2000 if len(parts) > 2 and parts[2] < 100 else 0) if len(parts) > 2 else None
        elif token.group("dm"):
            day = int(re.match(r"\d+", text).group(0))
            month = MONTHS[re.search(rf"({_MONTH})", text).group(1)]
            y = re.search(r"\d{4}", text)
            year = int(y.group(0)) if y else None
        else:
            month = MONTHS[re.match(r"[a-zä]+", text).group(0)]
            day = int(re.search(r"\d+", text).group(0))
        year = year or today.year
        candidate = date(year, month, day)
        return candidate if candidate >= today else date(year + 1, month, day)
    except (ValueError, KeyError, AttributeError):
        return None


def parse_slots(text: str, received: datetime, horizon_days: int = 21) -> list[Slot]:
    """Concrete (date, time) pairs offered in the text, in reading order.

    A time pairs with the most recent day mentioned before it; a day with no time after it
    yields nothing. Past slots and slots beyond the horizon are dropped.
    """
    slots: list[Slot] = []
    current: date | None = None
    for m in _TOKEN.finditer(text):
        if m.group("rel") or m.group("day") or m.group("dmy") or m.group("dm") or m.group("md"):
            current = _parse_date(m, received)
            continue
        if current is None:
            continue
        if m.group("range"):
            unit = m.group("ru")
            lo = _hour(int(m.group("r1")), unit, int(m.group("r1m") or 0))
            hi = _hour(int(m.group("r2")), unit, int(m.group("r2m") or 0))
            if lo and hi and hi > lo:
                slots.append(Slot(datetime.combine(current, time(*lo), BERLIN),
                                  datetime.combine(current, time(*hi), BERLIN)))
        else:
            hm = _hour(int(m.group("h") or m.group("h2")), m.group("u"),
                       int(m.group("m") or m.group("m2") or 0))
            if hm:
                slots.append(Slot(datetime.combine(current, time(*hm), BERLIN)))
    limit = received + timedelta(days=horizon_days)
    out = [s for s in slots if received <= s.start <= limit]
    return out[:MAX_SLOT_CANDIDATES]


def _window_bounds(day: date, a: Availability) -> list[tuple[datetime, datetime]]:
    if day in a.blackout_dates:
        return []
    wd = WEEKDAYS[day.weekday()]
    out = []
    for w in a.windows:
        if wd in w.days:
            s_h, s_m = (int(x) for x in w.start.split(":"))
            e_h, e_m = (int(x) for x in w.end.split(":"))
            out.append((datetime.combine(day, time(s_h, s_m), BERLIN),
                        datetime.combine(day, time(e_h, e_m), BERLIN)))
    return out


def fit_slot(slot: Slot, a: Availability, now: datetime) -> datetime | None:
    """Arrival time inside both the offered slot and your windows, or None.

    A fixed time must lie inside a window with room for the whole viewing; a range may start
    later than the window opens, and we arrive at the first moment both are free.
    """
    need = timedelta(minutes=a.viewing_minutes)
    earliest = now + timedelta(hours=a.min_notice_hours)
    for w_start, w_end in _window_bounds(slot.start.date(), a):
        if slot.end is None:
            if slot.start >= max(w_start, earliest) and slot.start + need <= w_end:
                return slot.start
            continue
        arrive = max(slot.start, w_start, earliest)
        if arrive + need <= min(slot.end, w_end):
            return arrive
    return None


def best_slot(slots: list[Slot], a: Availability, now: datetime) -> datetime | None:
    fits = [t for s in slots if (t := fit_slot(s, a, now))]
    return min(fits) if fits else None


def propose_slots(a: Availability, now: datetime, n: int = 3, horizon_days: int = 10) -> list[datetime]:
    """Up to n of your own free times, at most one per day, soonest first."""
    earliest = now + timedelta(hours=a.min_notice_hours)
    need = timedelta(minutes=a.viewing_minutes)
    out: list[datetime] = []
    day = earliest.astimezone(BERLIN).date()
    for _ in range(horizon_days):
        for w_start, w_end in sorted(_window_bounds(day, a)):
            arrive = max(w_start, earliest)
            if arrive + need <= w_end:
                out.append(arrive.replace(second=0, microsecond=0))
                break
        if len(out) == n:
            break
        day += timedelta(days=1)
    return out


def fmt_slot(t: datetime, lang: str) -> str:
    t = t.astimezone(BERLIN)
    if lang == "en":
        h12 = t.hour % 12 or 12
        minutes = f":{t.minute:02d}" if t.minute else ""
        suffix = "pm" if t.hour >= 12 else "am"
        return f"{EN_DAYS[t.weekday()]}, {t.day} {t.strftime('%b')} at {h12}{minutes} {suffix}"
    return f"{DE_DAYS[t.weekday()]}, {t:%d.%m.} um {t:%H:%M} Uhr"


def compose_reply(
    kind: str, lang: str, names: str, phone: str, slot: datetime | None,
    proposals: list[datetime] | None = None,
) -> str:
    """kind: 'confirm' (a slot that fits) or 'propose' (our own free times)."""
    de = lang != "en"
    if kind == "confirm" and slot:
        body = (f"Guten Tag,\n\nvielen Dank für Ihre Rückmeldung. Der Termin am {fmt_slot(slot, 'de')} "
                f"passt uns gut, wir kommen gern. Bei Fragen erreichen Sie uns unter {phone}.\n\n"
                f"Viele Grüße\n{names}" if de else
                f"Hello,\n\nthank you for getting back to us. {fmt_slot(slot, 'en')} works well for us, "
                f"we will be there. You can reach us at {phone}.\n\nKind regards\n{names}")
    else:
        options = "\n".join(f"- {fmt_slot(t, lang)}" for t in (proposals or []))
        body = (f"Guten Tag,\n\nvielen Dank für Ihre Rückmeldung. Wir kommen gern zu einer "
                f"Besichtigung vorbei. Bei uns passen folgende Zeiten:\n{options}\n"
                f"Sagen Sie gern, was Ihnen am besten passt. Sie erreichen uns unter {phone}.\n\n"
                f"Viele Grüße\n{names}" if de else
                f"Hello,\n\nthank you for getting back to us. We would be glad to view the flat. "
                f"These times work for us:\n{options}\nPlease let us know what suits you best. "
                f"You can reach us at {phone}.\n\nKind regards\n{names}")
    return body
