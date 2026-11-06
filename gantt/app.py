"""
Flask app for the gantt tool: staff-constrained Gantt charts stored behind token URLs.
"""

import os
import re
import secrets
from datetime import date, timedelta

from authentication import register_auth_context
from flask import Flask, abort, jsonify, redirect, render_template, request
from storage import StorageConflictError, get_storage

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
register_auth_context(app)

GANTT_NAMESPACE = "__gantt__"
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{43}")
ROW_KINDS = {"group", "task", "milestone"}
MAX_ROWS = 1000
MAX_TYPES = 32
MAX_EXCLUDED = 1000


def chart_file(token):
    """
    Return the storage filename for a chart token.
    """
    return f"{token}.json"


def next_monday():
    """
    Return the ISO date of the next Monday, or today if it is a Monday.
    """
    today = date.today()
    return (today + timedelta(days=(7 - today.weekday()) % 7)).isoformat()


def new_chart():
    """
    Return the contents of a freshly created chart.
    """
    return {
        "title": "Untitled chart",
        "start": next_monday(),
        "excluded": [],
        "types": [
            {
                "id": "eng",
                "abbr": "ENG",
                "name": "Engineer",
                "color": "blue",
                "limit": 2,
            }
        ],
        "rows": [],
    }


def load_document(token):
    """
    Load a chart document by token, returning (document, etag) or aborting with a 404.
    """
    if not TOKEN_RE.fullmatch(token):
        abort(404)
    result = get_storage().retrieve(GANTT_NAMESPACE, chart_file(token))
    if result is None:
        abort(404)
    return result


def is_iso_date(value):
    """
    Return whether value is an ISO format date string.
    """
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def is_valid_chart(chart):
    """
    Return whether a submitted chart has the structure the page relies on.
    """
    if not isinstance(chart, dict):
        return False
    title, rows, types, excluded = (
        chart.get("title"),
        chart.get("rows"),
        chart.get("types"),
        chart.get("excluded"),
    )
    if not isinstance(title, str) or not is_iso_date(chart.get("start")):
        return False
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        return False
    if not isinstance(types, list) or len(types) > MAX_TYPES:
        return False
    if not isinstance(excluded, list) or len(excluded) > MAX_EXCLUDED:
        return False
    return (
        all(
            isinstance(r, dict)
            and isinstance(r.get("id"), str)
            and r.get("kind") in ROW_KINDS
            for r in rows
        )
        and all(
            isinstance(t, dict)
            and isinstance(t.get("id"), str)
            and isinstance(t.get("limit"), int)
            for t in types
        )
        and all(isinstance(e, dict) and is_iso_date(e.get("week")) for e in excluded)
    )


@app.after_request
def hide_token_from_referrers(response):
    """
    Stop the secret token in the page URL leaking to other sites via the Referer header.
    """
    response.headers["Referrer-Policy"] = "same-origin"
    return response


@app.route("/")
def index():
    """
    Show the landing page.
    """
    return render_template("index.html")


@app.route("/new", methods=["POST"])
def new():
    """
    Create a new chart and redirect to its token URL.
    """
    token = secrets.token_urlsafe(32)
    get_storage().store(
        GANTT_NAMESPACE, chart_file(token), {"rev": 1, "chart": new_chart()}
    )
    return redirect(f"/{token}", code=303)


@app.route("/<token>")
def chart_page(token):
    """
    Show a chart.
    """
    document, _ = load_document(token)
    return render_template(
        "chart.html", token=token, rev=document["rev"], chart=document["chart"]
    )


@app.route("/<token>/data", methods=["PUT"])
def chart_save(token):
    """
    Save a chart, refusing the write if it was based on an outdated revision.
    """
    document, etag = load_document(token)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not is_valid_chart(payload.get("chart")):
        return jsonify({"error": "invalid chart"}), 400
    if payload.get("rev") != document["rev"]:
        return jsonify({"error": "conflict", "rev": document["rev"]}), 409
    rev = document["rev"] + 1
    try:
        get_storage().store(
            GANTT_NAMESPACE,
            chart_file(token),
            {"rev": rev, "chart": payload["chart"]},
            version=etag,
        )
    except StorageConflictError:
        return jsonify({"error": "conflict"}), 409
    return jsonify({"rev": rev})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
