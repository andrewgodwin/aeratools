"""
Flask app for the chores tool: track recurring chores with schedules and due dates.
"""

import os
import re
import secrets
from datetime import date, timedelta

from authentication import get_current_user, register_auth_context, require_auth
from flask import Flask, abort, redirect, render_template, request
from storage import StorageConflictError, get_storage

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")
register_auth_context(app)

CHORES_FILE = "chores.json"
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def empty_data():
    """
    Return an empty chores data structure.
    """
    return {"lists": [], "chores": []}


def load_data(user):
    """
    Load the user's chores data from storage, returning (data, etag).
    """
    result = get_storage().retrieve(user, CHORES_FILE)
    if result is None:
        return empty_data(), None
    return result


def find_list(data, slug):
    """
    Find a list by its URL slug, returning the list dict or None.
    """
    for lst in data["lists"]:
        if lst["slug"] == slug:
            return lst
    return None


def find_chore(data, chore_id):
    """
    Find a chore by its ID, returning the chore dict or None.
    """
    for chore in data["chores"]:
        if chore["id"] == chore_id:
            return chore
    return None


def slugify(name):
    """
    Convert a list name to a URL-safe slug.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "list"


def ensure_unique_slug(data, base_slug, exclude_id=None):
    """
    Return a unique slug among existing lists, appending a number if needed.
    """
    existing = {lst["slug"] for lst in data["lists"] if lst.get("id") != exclude_id}
    slug = base_slug
    i = 2
    while slug in existing:
        slug = f"{base_slug}-{i}"
        i += 1
    return slug


def compute_due_date(chore):
    """
    Compute the next due date for a chore, accounting for completions and vanish rules.
    """
    today = date.today()
    schedule_type = chore["schedule_type"]
    last_completed_str = chore.get("last_completed")
    last_completed = None
    if last_completed_str:
        last_completed = date.fromisoformat(last_completed_str[:10])

    if schedule_type == "relative":
        days = chore["schedule"]["days"]
        if last_completed:
            return last_completed + timedelta(days=days)
        return today  # Due immediately if never completed

    elif schedule_type == "fixed_weekday":
        weekdays = set(chore["schedule"]["weekdays"])

        # Find the most recent scheduled occurrence on or before today
        current_cycle = None
        for offset in range(7):
            candidate = today - timedelta(days=offset)
            if candidate.weekday() in weekdays:
                current_cycle = candidate
                break

        # If completed after the current cycle date, we're done — find next occurrence
        if last_completed and current_cycle and last_completed >= current_cycle:
            for offset in range(1, 8):
                candidate = today + timedelta(days=offset)
                if candidate.weekday() in weekdays:
                    return candidate

        # Overdue and should vanish? Skip to next occurrence
        if current_cycle and current_cycle < today and chore.get("vanish_if_missed"):
            for offset in range(1, 8):
                candidate = today + timedelta(days=offset)
                if candidate.weekday() in weekdays:
                    return candidate

        return current_cycle or today

    elif schedule_type == "fixed_biweekly":
        weekday = chore["schedule"]["weekday"]
        created = date.fromisoformat(chore["created_at"][:10])

        # Anchor: first occurrence of the weekday on or after the creation date
        days_ahead = (weekday - created.weekday()) % 7
        anchor = created + timedelta(days=days_ahead)

        # Find the most recent "on" occurrence on or before today
        current_cycle = None
        for offset in range(14):
            candidate = today - timedelta(days=offset)
            if candidate.weekday() == weekday and (candidate - anchor).days % 14 == 0:
                current_cycle = candidate
                break

        if current_cycle is None:
            # First due date hasn't arrived yet — find the next "on" occurrence
            for offset in range(1, 15):
                candidate = today + timedelta(days=offset)
                if (
                    candidate.weekday() == weekday
                    and (candidate - anchor).days % 14 == 0
                ):
                    return candidate
            return anchor  # Fallback (anchor is always within 14 days of today)

        # If completed after the current cycle date, we're done — next is 14 days later
        if last_completed and last_completed >= current_cycle:
            return current_cycle + timedelta(days=14)

        # Overdue and should vanish? Skip to next occurrence
        if current_cycle < today and chore.get("vanish_if_missed"):
            for offset in range(1, 15):
                candidate = today + timedelta(days=offset)
                if (
                    candidate.weekday() == weekday
                    and (candidate - anchor).days % 14 == 0
                ):
                    return candidate

        return current_cycle

    return today  # Fallback for unknown schedule types


def build_due_info(chore):
    """
    Return a dict with due date, status string, and display label for a chore.
    """
    today = date.today()
    due = compute_due_date(chore)
    delta = (due - today).days

    if delta < 0:
        days = abs(delta)
        label = f"overdue {days} day{'s' if days != 1 else ''}"
        status = "overdue"
    elif delta == 0:
        label = "due today"
        status = "today"
    elif delta == 1:
        label = "due tomorrow"
        status = "future"
    elif delta < 7:
        label = f"due in {delta} days"
        status = "future"
    elif delta < 14:
        label = "due next week"
        status = "future"
    else:
        weeks = delta // 7
        label = f"due in {weeks} week{'s' if weeks != 1 else ''}"
        status = "future"

    return {"date": due, "label": label, "status": status}


def is_snoozed(chore):
    """
    Return True if the chore is currently snoozed.
    """
    snoozed_until = chore.get("snoozed_until")
    if not snoozed_until:
        return False
    return date.today() <= date.fromisoformat(snoozed_until)


def get_sorted_chores(data, list_id):
    """
    Return chores that are due today or overdue, sorted by priority then due date.
    """
    today = date.today()
    chores_with_info = []
    for chore in data["chores"]:
        if chore["list_id"] != list_id:
            continue
        if is_snoozed(chore):
            continue
        info = build_due_info(chore)
        if info["date"] > today:
            continue
        chores_with_info.append((chore, info))

    chores_with_info.sort(
        key=lambda x: (PRIORITY_ORDER.get(x[0]["priority"], 1), x[1]["date"])
    )
    return chores_with_info


def parse_schedule_from_form(form, schedule_type):
    """
    Parse and return a schedule dict from submitted form data.
    """
    if schedule_type == "relative":
        try:
            amount = int(form.get("relative_amount", 7))
        except (ValueError, TypeError):
            amount = 7
        unit = form.get("relative_unit", "days")
        days = amount * 7 if unit == "weeks" else amount
        return {"days": max(1, days)}
    elif schedule_type == "fixed_weekday":
        weekdays = []
        for i in range(7):
            if form.get(f"weekday_{i}"):
                weekdays.append(i)
        return {"weekdays": weekdays or [0]}  # Default to Monday
    elif schedule_type == "fixed_biweekly":
        try:
            weekday = int(form.get("biweekly_weekday", 0))
        except (ValueError, TypeError):
            weekday = 0
        return {"weekday": weekday % 7}
    return {}


@app.template_filter("schedule_label")
def schedule_label(chore):
    """
    Return a human-readable description of a chore's schedule.
    """
    stype = chore["schedule_type"]
    if stype == "relative":
        days = chore["schedule"]["days"]
        if days % 7 == 0:
            weeks = days // 7
            return f"every {weeks} week{'s' if weeks != 1 else ''}"
        return f"every {days} day{'s' if days != 1 else ''}"
    elif stype == "fixed_weekday":
        names = [WEEKDAY_NAMES[d] for d in sorted(chore["schedule"]["weekdays"])]
        return "every " + " & ".join(names)
    elif stype == "fixed_biweekly":
        name = WEEKDAY_NAMES[chore["schedule"]["weekday"]]
        return f"every other {name}"
    return "unknown schedule"


# ── Routes ──────────────────────────────────────────────────────────────────


@app.route("/")
@require_auth
def index():
    """
    Redirect to first list, or show empty state if no lists exist.
    """
    user = get_current_user()
    data, _ = load_data(user)
    if data["lists"]:
        return redirect(f"/list/{data['lists'][0]['slug']}")
    return render_template("index.html", all_lists=[])


@app.route("/list/<slug>")
@require_auth
def view_list(slug):
    """
    Display all visible chores in a list, sorted by priority and due date.
    """
    user = get_current_user()
    data, _ = load_data(user)
    lst = find_list(data, slug)
    if lst is None:
        abort(404)
    chores = get_sorted_chores(data, lst["id"])
    return render_template(
        "list.html", list=lst, chores=chores, all_lists=data["lists"]
    )


@app.route("/list/<slug>/complete/<chore_id>", methods=["POST"])
@require_auth
def complete_chore(slug, chore_id):
    """
    Mark a chore as done, recording today's date as the completion.
    """
    user = get_current_user()
    storage = get_storage()
    for _ in range(5):
        result = storage.retrieve(user, CHORES_FILE)
        if result is None:
            abort(404)
        data, etag = result
        chore = find_chore(data, chore_id)
        if chore is None:
            abort(404)
        chore["last_completed"] = date.today().isoformat()
        chore["snoozed_until"] = None
        try:
            storage.store(user, CHORES_FILE, data, version=etag)
            break
        except StorageConflictError:
            continue
    return redirect(f"/list/{slug}")


@app.route("/list/<slug>/snooze/<chore_id>", methods=["POST"])
@require_auth
def snooze_chore(slug, chore_id):
    """
    Snooze a chore until a specified date, hiding it from the list until then.
    """
    today = date.today()
    if request.form.get("use_date"):
        until_str = request.form.get("until_date", "")
        if not until_str:
            return redirect(f"/list/{slug}")
        snooze_until = until_str
    elif request.form.get("days"):
        try:
            days = int(request.form["days"])
        except (ValueError, TypeError):
            return redirect(f"/list/{slug}")
        snooze_until = (today + timedelta(days=days)).isoformat()
    else:
        return redirect(f"/list/{slug}")

    user = get_current_user()
    storage = get_storage()
    for _ in range(5):
        result = storage.retrieve(user, CHORES_FILE)
        if result is None:
            abort(404)
        data, etag = result
        chore = find_chore(data, chore_id)
        if chore is None:
            abort(404)
        chore["snoozed_until"] = snooze_until
        try:
            storage.store(user, CHORES_FILE, data, version=etag)
            break
        except StorageConflictError:
            continue
    return redirect(f"/list/{slug}")


@app.route("/list/<slug>/edit")
@require_auth
def edit_list(slug):
    """
    Show the list edit page with rename/delete controls and a table of chores.
    """
    user = get_current_user()
    data, _ = load_data(user)
    lst = find_list(data, slug)
    if lst is None:
        abort(404)
    chores = [c for c in data["chores"] if c["list_id"] == lst["id"]]
    return render_template(
        "edit.html", list=lst, chores=chores, all_lists=data["lists"]
    )


@app.route("/list/new", methods=["POST"])
@require_auth
def new_list():
    """
    Create a new chore list and redirect to it.
    """
    name = request.form.get("name", "").strip()
    if not name:
        return redirect("/")
    user = get_current_user()
    storage = get_storage()
    slug = None
    for _ in range(5):
        result = storage.retrieve(user, CHORES_FILE)
        if result is None:
            data, etag = empty_data(), None
        else:
            data, etag = result
        base_slug = slugify(name)
        slug = ensure_unique_slug(data, base_slug)
        data["lists"].append(
            {"id": secrets.token_urlsafe(8), "name": name, "slug": slug}
        )
        try:
            storage.store(user, CHORES_FILE, data, version=etag)
            return redirect(f"/list/{slug}")
        except StorageConflictError:
            continue
    return redirect("/")


@app.route("/list/<slug>/rename", methods=["POST"])
@require_auth
def rename_list(slug):
    """
    Rename a chore list, updating its slug if needed.
    """
    name = request.form.get("name", "").strip()
    if not name:
        return redirect(f"/list/{slug}/edit")
    user = get_current_user()
    storage = get_storage()
    for _ in range(5):
        result = storage.retrieve(user, CHORES_FILE)
        if result is None:
            abort(404)
        data, etag = result
        lst = find_list(data, slug)
        if lst is None:
            abort(404)
        new_slug = ensure_unique_slug(data, slugify(name), exclude_id=lst["id"])
        lst["name"] = name
        lst["slug"] = new_slug
        try:
            storage.store(user, CHORES_FILE, data, version=etag)
            return redirect(f"/list/{new_slug}/edit")
        except StorageConflictError:
            continue
    return redirect(f"/list/{slug}/edit")


@app.route("/list/<slug>/delete", methods=["POST"])
@require_auth
def delete_list(slug):
    """
    Delete a chore list and all its chores, then redirect to the next list.
    """
    user = get_current_user()
    storage = get_storage()
    for _ in range(5):
        result = storage.retrieve(user, CHORES_FILE)
        if result is None:
            abort(404)
        data, etag = result
        lst = find_list(data, slug)
        if lst is None:
            abort(404)
        list_id = lst["id"]
        data["lists"] = [lst for lst in data["lists"] if lst["id"] != list_id]
        data["chores"] = [c for c in data["chores"] if c["list_id"] != list_id]
        try:
            storage.store(user, CHORES_FILE, data, version=etag)
            if data["lists"]:
                return redirect(f"/list/{data['lists'][0]['slug']}")
            return redirect("/")
        except StorageConflictError:
            continue
    return redirect("/")


@app.route("/chore/new", methods=["GET", "POST"])
@require_auth
def new_chore():
    """
    Show or handle the form for creating a new chore.
    """
    user = get_current_user()
    data, _ = load_data(user)
    list_slug = request.args.get("list") or request.form.get("list_slug", "")
    default_list = find_list(data, list_slug) or (
        data["lists"][0] if data["lists"] else None
    )

    if request.method == "GET":
        return render_template(
            "chore_form.html", chore=None, list=default_list, all_lists=data["lists"]
        )

    title = request.form.get("title", "").strip()
    if not title:
        return render_template(
            "chore_form.html",
            chore=None,
            list=default_list,
            all_lists=data["lists"],
            error="Title is required.",
        )

    priority = request.form.get("priority", "medium")
    schedule_type = request.form.get("schedule_type", "relative")
    vanish = bool(request.form.get("vanish_if_missed"))
    schedule = parse_schedule_from_form(request.form, schedule_type)
    target_slug = request.form.get("list_slug", list_slug)

    storage = get_storage()
    for _ in range(5):
        result = storage.retrieve(user, CHORES_FILE)
        if result is None:
            data, etag = empty_data(), None
        else:
            data, etag = result
        lst = find_list(data, target_slug)
        if lst is None:
            abort(404)
        chore = {
            "id": secrets.token_urlsafe(8),
            "list_id": lst["id"],
            "title": title,
            "priority": priority,
            "schedule_type": schedule_type,
            "schedule": schedule,
            "vanish_if_missed": vanish,
            "last_completed": None,
            "snoozed_until": None,
            "created_at": date.today().isoformat(),
        }
        data["chores"].append(chore)
        try:
            storage.store(user, CHORES_FILE, data, version=etag)
            return redirect(f"/list/{target_slug}")
        except StorageConflictError:
            continue
    return redirect(f"/list/{target_slug}")


@app.route("/chore/<chore_id>/edit", methods=["GET", "POST"])
@require_auth
def edit_chore(chore_id):
    """
    Show or handle the form for editing an existing chore.
    """
    user = get_current_user()
    data, _ = load_data(user)
    chore = find_chore(data, chore_id)
    if chore is None:
        abort(404)
    lst = next((item for item in data["lists"] if item["id"] == chore["list_id"]), None)

    if request.method == "GET":
        return render_template(
            "chore_form.html", chore=chore, list=lst, all_lists=data["lists"]
        )

    title = request.form.get("title", "").strip()
    if not title:
        return render_template(
            "chore_form.html",
            chore=chore,
            list=lst,
            all_lists=data["lists"],
            error="Title is required.",
        )

    schedule_type = request.form.get("schedule_type", chore["schedule_type"])
    schedule = parse_schedule_from_form(request.form, schedule_type)
    last_completed = request.form.get("last_completed", "").strip() or None

    storage = get_storage()
    for _ in range(5):
        result = storage.retrieve(user, CHORES_FILE)
        if result is None:
            abort(404)
        data, etag = result
        c = find_chore(data, chore_id)
        if c is None:
            abort(404)
        c["title"] = title
        c["priority"] = request.form.get("priority", c["priority"])
        c["schedule_type"] = schedule_type
        c["schedule"] = schedule
        c["vanish_if_missed"] = bool(request.form.get("vanish_if_missed"))
        c["last_completed"] = last_completed
        try:
            storage.store(user, CHORES_FILE, data, version=etag)
            if lst:
                return redirect(f"/list/{lst['slug']}")
            return redirect("/")
        except StorageConflictError:
            continue
    if lst:
        return redirect(f"/list/{lst['slug']}")
    return redirect("/")


@app.route("/chore/<chore_id>/delete", methods=["POST"])
@require_auth
def delete_chore(chore_id):
    """
    Delete a chore and redirect to its list's edit page.
    """
    user = get_current_user()
    storage = get_storage()
    redirect_slug = None
    for _ in range(5):
        result = storage.retrieve(user, CHORES_FILE)
        if result is None:
            abort(404)
        data, etag = result
        chore = find_chore(data, chore_id)
        if chore is None:
            abort(404)
        lst = next(
            (item for item in data["lists"] if item["id"] == chore["list_id"]), None
        )
        redirect_slug = lst["slug"] if lst else None
        data["chores"] = [c for c in data["chores"] if c["id"] != chore_id]
        try:
            storage.store(user, CHORES_FILE, data, version=etag)
            break
        except StorageConflictError:
            continue
    if redirect_slug:
        return redirect(f"/list/{redirect_slug}/edit")
    return redirect("/")


@app.route("/chore/<chore_id>/uncomplete", methods=["POST"])
@require_auth
def uncomplete_chore(chore_id):
    """
    Clear the last completion record from a chore, marking it as never done.
    """
    user = get_current_user()
    storage = get_storage()
    redirect_slug = None
    for _ in range(5):
        result = storage.retrieve(user, CHORES_FILE)
        if result is None:
            abort(404)
        data, etag = result
        chore = find_chore(data, chore_id)
        if chore is None:
            abort(404)
        lst = next(
            (item for item in data["lists"] if item["id"] == chore["list_id"]), None
        )
        redirect_slug = lst["slug"] if lst else None
        chore["last_completed"] = None
        try:
            storage.store(user, CHORES_FILE, data, version=etag)
            break
        except StorageConflictError:
            continue
    if redirect_slug:
        return redirect(f"/list/{redirect_slug}/edit")
    return redirect("/")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
