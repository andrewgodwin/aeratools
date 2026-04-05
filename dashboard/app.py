"""
Flask app for the dashboard tool: persist widget configurations server-side.
"""

import os
import secrets

from authentication import get_current_user, register_auth_context
from flask import Flask, abort, jsonify, render_template, request
from storage import get_storage

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")
register_auth_context(app)

DASHBOARD_NAMESPACE = "__dashboard__"
EMPTY_CONFIG: dict = {"header": [], "left": [], "right": []}


def _valid_config(cfg):
    """
    Return True if cfg is a dict with header/left/right lists of valid entries.
    """
    if not isinstance(cfg, dict):
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
    get_storage().store(DASHBOARD_NAMESPACE, f"{dashboard_id}.json", cfg)

    return jsonify({"id": dashboard_id}), 201


@app.route("/<dashboard_id>")
def view_dashboard(dashboard_id):
    """
    View a saved dashboard by ID; publicly accessible.
    """
    result = get_storage().retrieve(DASHBOARD_NAMESPACE, f"{dashboard_id}.json")
    if result is None:
        abort(404)
    config, _ = result
    return render_template("index.html", config=config, dashboard_id=dashboard_id)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
