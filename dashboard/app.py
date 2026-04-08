"""
Flask app for the dashboard tool: persist widget configurations server-side.
"""

import os
import secrets

from authentication import get_current_user, register_auth_context
from flask import Flask, abort, jsonify, redirect, render_template, request
from storage import get_storage

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")
register_auth_context(app)

DASHBOARD_PREFIX = "dashboard_"
EMPTY_CONFIG: dict = {"header": [], "left": [], "right": []}


def _valid_config(cfg):
    """
    Return True if cfg is a dict with optional name and header/left/right lists of valid
    entries.
    """
    if not isinstance(cfg, dict):
        return False
    if "name" in cfg and not isinstance(cfg["name"], str):
        return False
    for section in ("header", "left", "right"):
        if not isinstance(cfg.get(section), list):
            return False
        for entry in cfg[section]:
            if not isinstance(entry, dict):
                return False
            if not isinstance(entry.get("url"), str):
                return False
            if not isinstance(entry.get("height", 400), (int, float)):
                return False
    return True


@app.route("/", methods=["GET"])
def index():
    """
    Home page: render an empty dashboard ready for configuration.
    """
    return render_template("index.html", config=EMPTY_CONFIG, dashboard_id=None)


@app.route("/", methods=["POST"])
def save_config():
    """
    Save a new dashboard config; requires authentication.
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Sign in to save your dashboard"}), 401

    try:
        cfg = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    if not _valid_config(cfg):
        return jsonify({"error": "Invalid config structure"}), 400

    dashboard_id = secrets.token_urlsafe(31)
    get_storage().store(user, f"{DASHBOARD_PREFIX}{dashboard_id}.json", cfg)

    return jsonify({"id": dashboard_id}), 201


def _auth_redirect():
    """
    Return a redirect response to the auth tool for unauthenticated requests.
    """
    root_domain = app.config["ROOT_DOMAIN"]
    auth_base = f"https://auth.{root_domain}" if root_domain else "/auth"
    return redirect(f"{auth_base}/?next={request.url}")


@app.route("/my-dashboards")
def my_dashboards():
    """
    List all dashboards belonging to the current user; requires authentication.
    """
    user = get_current_user()
    if not user:
        return _auth_redirect()
    files = get_storage().list(user, prefix=DASHBOARD_PREFIX)
    dashboards = []
    for f in files:
        if not f.endswith(".json"):
            continue
        dashboard_id = f[len(DASHBOARD_PREFIX) : -len(".json")]
        result = get_storage().retrieve(user, f)
        name = result[0].get("name", "") if result else ""
        dashboards.append({"id": dashboard_id, "name": name or dashboard_id})
    return render_template("my_dashboards.html", dashboards=dashboards)


@app.route("/<dashboard_id>", methods=["PUT"])
def update_dashboard(dashboard_id):
    """
    Overwrite an existing dashboard config; requires authentication.
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Sign in to save your dashboard"}), 401

    existing = get_storage().retrieve(user, f"{DASHBOARD_PREFIX}{dashboard_id}.json")
    if existing is None:
        abort(404)

    try:
        cfg = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    if not _valid_config(cfg):
        return jsonify({"error": "Invalid config structure"}), 400

    get_storage().store(user, f"{DASHBOARD_PREFIX}{dashboard_id}.json", cfg)
    return jsonify({"id": dashboard_id}), 200


@app.route("/<dashboard_id>")
def view_dashboard(dashboard_id):
    """
    View a saved dashboard by ID; requires authentication.
    """
    user = get_current_user()
    if not user:
        return _auth_redirect()
    result = get_storage().retrieve(user, f"{DASHBOARD_PREFIX}{dashboard_id}.json")
    if result is None:
        abort(404)
    config, _ = result
    return render_template("index.html", config=config, dashboard_id=dashboard_id)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
