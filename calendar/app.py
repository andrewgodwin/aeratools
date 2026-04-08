import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote

import requests
from authentication import register_auth_context
from dateutil.rrule import rrule as rrule_type
from dateutil.rrule import rruleset, rrulestr
from flask import Flask, jsonify, render_template, request
from icalendar import Calendar

app = Flask(__name__)
register_auth_context(app)

# In-memory cache: url -> (fetched_at, raw_bytes)
_cache: dict[str, tuple[float, bytes]] = {}
_cache_lock = threading.Lock()
CACHE_TTL = 1800  # seconds (30 minutes)


def fetch_ical(url: str) -> bytes:
    """
    Fetch and cache raw iCal bytes for a URL, respecting the 30-minute TTL.

    Falls back to the cached version if a fresh fetch fails.
    """
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(url)
        if entry and (now - entry[0]) < CACHE_TTL:
            return entry[1]
        stale = entry[1] if entry else None
    try:
        resp = requests.get(
            url, timeout=10, headers={"User-Agent": "aeratools-calendar/1.0"}
        )
        resp.raise_for_status()
        data = resp.content
        with _cache_lock:
            _cache[url] = (now, data)
        return data
    except Exception:
        if stale is not None:
            return stale
        raise


def to_utc_dt(dt_value) -> datetime:
    """
    Convert a date or datetime to a UTC-aware datetime.
    """
    if isinstance(dt_value, datetime):
        if dt_value.tzinfo is None:
            return dt_value.replace(tzinfo=timezone.utc)
        return dt_value.astimezone(timezone.utc)
    # date-only → treat as midnight UTC
    return datetime(dt_value.year, dt_value.month, dt_value.day, tzinfo=timezone.utc)


def is_date_only(value) -> bool:
    """
    Return True only for date objects, not datetime (which subclasses date).
    """
    return isinstance(value, date) and not isinstance(value, datetime)


def google_calendar_owner(url: str) -> str | None:
    """
    Extract the owner's email from a Google Calendar iCal URL, or None.
    """
    m = re.search(r"calendar\.google\.com/calendar/ical/([^/]+)/private-", url)
    return unquote(m.group(1)).lower() if m else None


def event_is_declined(component, owner_email: str | None) -> bool:
    """
    Return True if the calendar owner declined this event.

    Checks TRANSP:TRANSPARENT (Apple/Outlook) and, when the owner's email is known,
    ATTENDEE;PARTSTAT=DECLINED (Google Calendar).
    """
    transp = component.get("TRANSP")
    if transp and str(transp).upper() == "TRANSPARENT":
        return True

    if owner_email:
        attendees = component.get("ATTENDEE")
        if attendees is not None:
            if not isinstance(attendees, list):
                attendees = [attendees]
            for att in attendees:
                addr = str(att).lower().replace("mailto:", "").strip()
                if addr == owner_email:
                    partstat = str(att.params.get("PARTSTAT", "")).upper()
                    return partstat == "DECLINED"

    return False


def parse_feed(
    url: str, color: str, window_start: datetime, window_end: datetime
) -> list[dict]:
    """
    Parse an iCal feed and return events overlapping the given UTC window.

    Handles RECURRENCE-ID overrides to prevent duplicate events and ghost occurrences on
    the original date of a modified recurring instance.
    """
    owner_email = google_calendar_owner(url)
    data = fetch_ical(url)
    cal = Calendar.from_ical(data)
    components = list(cal.walk("VEVENT"))

    # First pass: collect RECURRENCE-ID overrides so we can exclude their
    # original dates from RRULE expansion of the master event.
    override_dates: dict[str, list[datetime]] = {}  # uid -> [original UTC datetimes]
    masters: list = []
    overrides: list = []

    for comp in components:
        if comp.get("RECURRENCE-ID"):
            uid = str(comp.get("UID", ""))
            rid = comp.get("RECURRENCE-ID").dt
            rid_utc = to_utc_dt(rid)
            override_dates.setdefault(uid, []).append(rid_utc)
            overrides.append(comp)
        else:
            masters.append(comp)

    events: list[dict] = []

    # Second pass: process masters first, then overrides as single events.
    for component in masters + overrides:
        dtstart_prop = component.get("DTSTART")
        if not dtstart_prop:
            continue

        raw_start = dtstart_prop.dt
        all_day = is_date_only(raw_start)

        if event_is_declined(component, owner_email):
            continue

        # Determine raw end or derive from DURATION / defaults.
        dtend_prop = component.get("DTEND")
        duration_prop = component.get("DURATION")
        if dtend_prop:
            raw_end = dtend_prop.dt
        elif duration_prop:
            raw_end = raw_start + duration_prop.dt
        else:
            raw_end = raw_start + (timedelta(days=1) if all_day else timedelta(hours=1))

        def build_event(start, end, _all_day=all_day, _comp=component):
            """
            Build a JSON-serialisable event dict for one occurrence.
            """
            if _all_day:
                # Always emit YYYY-MM-DD, regardless of whether start/end are
                # date or datetime objects (datetime subclasses date in Python).
                s = (
                    start.date().isoformat()
                    if isinstance(start, datetime)
                    else start.isoformat()
                )
                e = (
                    end.date().isoformat()
                    if isinstance(end, datetime)
                    else end.isoformat()
                )
            else:
                s = to_utc_dt(start).isoformat()
                e = to_utc_dt(end).isoformat()
            return {
                "title": str(_comp.get("SUMMARY", "") or "(No title)"),
                "start": s,
                "end": e,
                "allDay": _all_day,
                "color": color,
                "description": str(_comp.get("DESCRIPTION", "") or ""),
                "location": str(_comp.get("LOCATION", "") or ""),
                "url": str(_comp.get("URL", "") or ""),
            }

        rrule_prop = component.get("RRULE")
        is_override = bool(component.get("RECURRENCE-ID"))

        if rrule_prop and not is_override:
            # Recurring master event: expand occurrences within the window.
            if all_day:
                dtstart_dt = datetime(
                    raw_start.year, raw_start.month, raw_start.day, tzinfo=timezone.utc
                )
                duration = (
                    timedelta(days=(raw_end - raw_start).days)
                    if is_date_only(raw_end)
                    else timedelta(days=1)
                )
            else:
                # Keep original timezone so RRULE BYDAY/BYMONTHDAY expansion
                # aligns with the local calendar date, not the UTC equivalent.
                # Converting to UTC first can shift the weekday (e.g. midnight
                # BST becomes 23:00 UTC on the previous day).
                if isinstance(raw_start, datetime) and raw_start.tzinfo:
                    dtstart_dt = raw_start
                elif isinstance(raw_start, datetime):
                    dtstart_dt = raw_start.replace(tzinfo=timezone.utc)
                else:
                    dtstart_dt = datetime(
                        raw_start.year,
                        raw_start.month,
                        raw_start.day,
                        tzinfo=timezone.utc,
                    )
                # Duration measured in absolute wall-clock time.
                duration = to_utc_dt(raw_end) - to_utc_dt(raw_start)

            rule_str = rrule_prop.to_ical().decode()
            rs = rruleset()
            try:
                parsed = rrulestr(rule_str, dtstart=dtstart_dt, ignoretz=False)
                if not isinstance(parsed, rrule_type):
                    continue
                rs.rrule(parsed)
            except Exception:
                continue

            # EXDATEs declared in the event itself.
            exdate_prop = component.get("EXDATE")
            if exdate_prop:
                if not isinstance(exdate_prop, list):
                    exdate_prop = [exdate_prop]
                for exd in exdate_prop:
                    for d in exd.dts:
                        rs.exdate(to_utc_dt(d.dt))

            # EXDATEs from RECURRENCE-ID overrides — exclude the original
            # date so we don't emit a ghost occurrence alongside the override.
            uid = str(component.get("UID", ""))
            for rid_dt in override_dates.get(uid, []):
                rs.exdate(rid_dt)

            for occ in rs.between(window_start - duration, window_end, inc=True):
                occ_end = occ + duration
                if occ_end > window_start and occ < window_end:
                    events.append(build_event(occ, occ_end))
        else:
            # Single event or modified override instance — no RRULE expansion.
            if all_day:
                ev_start = to_utc_dt(raw_start)
                ev_end = to_utc_dt(raw_end)
            else:
                ev_start = to_utc_dt(raw_start)
                ev_end = to_utc_dt(raw_end)

            if ev_end > window_start and ev_start < window_end:
                events.append(build_event(raw_start, raw_end))

    return events


@app.route("/")
def index():
    """
    Render the calendar single-page app.
    """
    return render_template("index.html")


@app.route("/api/events")
def api_events():
    """
    Return events for all configured calendars within the requested date window.
    """
    cal_urls = request.args.getlist("cal")
    colors = request.args.getlist("color")
    start_str = request.args.get("start", "")
    end_str = request.args.get("end", "")

    if not start_str or not end_str:
        return jsonify({"events": [], "errors": []}), 400

    try:
        window_start = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
        window_end = datetime.fromisoformat(end_str).replace(tzinfo=timezone.utc)
    except ValueError:
        return jsonify({"events": [], "errors": ["Invalid start/end dates"]}), 400

    all_events = []
    errors = []

    for i, url in enumerate(cal_urls):
        color = colors[i] if i < len(colors) else "#7eb8f7"
        try:
            events = parse_feed(url, color, window_start, window_end)
            all_events.extend(events)
        except Exception as e:
            errors.append({"url": url, "error": str(e)})

    return jsonify({"events": all_events, "errors": errors})
