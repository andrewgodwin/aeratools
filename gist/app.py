"""
Flask app for the gist tool: create, view, edit, and delete markdown gists.
"""

import os
import secrets
import time
from datetime import datetime

import markdown as md_lib
import nh3
from authentication import get_current_user, register_auth_context, require_auth
from flask import Flask, abort, redirect, render_template, request
from markupsafe import Markup
from storage import StorageConflictError, get_storage

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")
register_auth_context(app)

GIST_NAMESPACE = "__gist__"

ALLOWED_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "br",
    "hr",
    "strong",
    "em",
    "del",
    "s",
    "a",
    "ul",
    "ol",
    "li",
    "blockquote",
    "code",
    "pre",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}

ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "th": {"align"},
    "td": {"align"},
}


@app.template_filter("datetimeformat")
def datetimeformat(value):
    """
    Format a Unix timestamp as a human-readable date string.
    """
    return datetime.utcfromtimestamp(value).strftime("%Y-%m-%d")


def render_markdown(content):
    """
    Render markdown to sanitized HTML.
    """
    html = md_lib.markdown(content, extensions=["fenced_code", "tables"])
    return Markup(nh3.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES))


def _update_user_index(storage, user, gist_id, title, created_at, action):
    """
    Update the user's gist index, retrying on optimistic concurrency conflicts.
    """
    for _ in range(5):
        result = storage.retrieve(user, "gists.json")
        if result is None:
            index, etag = {"gists": []}, None
        else:
            index, etag = result

        if action == "add":
            index["gists"].insert(
                0, {"id": gist_id, "title": title, "created_at": created_at}
            )
        elif action == "remove":
            index["gists"] = [g for g in index["gists"] if g["id"] != gist_id]
        elif action == "update_title":
            for g in index["gists"]:
                if g["id"] == gist_id:
                    g["title"] = title
                    break

        try:
            storage.store(user, "gists.json", index, version=etag)
            return
        except StorageConflictError:
            continue

    # Last resort: store without version check
    storage.store(user, "gists.json", index)


@app.route("/")
def index():
    """Home page: My Gists list for logged-in users, login prompt otherwise."""
    user = get_current_user()
    gists = []
    if user:
        result = get_storage().retrieve(user, "gists.json")
        if result:
            gists = result[0].get("gists", [])
    return render_template("index.html", gists=gists)


@app.route("/new", methods=["GET", "POST"])
@require_auth
def new_gist():
    """
    Create a new gist.
    """
    if request.method == "GET":
        return render_template("edit.html", gist=None, gist_id=None)

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()

    if not content:
        return render_template(
            "edit.html", gist=None, gist_id=None, error="Content is required."
        )

    user = get_current_user()
    now = int(time.time())
    gist_id = secrets.token_urlsafe(31)

    gist = {
        "title": title or "Untitled",
        "content": content,
        "created_by": user,
        "created_at": now,
        "updated_at": now,
        "hide_email": bool(request.form.get("hide_email")),
    }

    storage = get_storage()
    storage.store(GIST_NAMESPACE, f"{gist_id}.json", gist)
    _update_user_index(storage, user, gist_id, gist["title"], now, action="add")

    return redirect(f"/{gist_id}")


@app.route("/<gist_id>")
def view_gist(gist_id):
    """
    View a gist by ID; publicly accessible.
    """
    result = get_storage().retrieve(GIST_NAMESPACE, f"{gist_id}.json")
    if result is None:
        abort(404)
    gist, _ = result
    user = get_current_user()
    rendered = render_markdown(gist["content"])
    is_owner = user is not None and user == gist.get("created_by")
    return render_template(
        "view.html", gist=gist, gist_id=gist_id, rendered=rendered, is_owner=is_owner
    )


@app.route("/<gist_id>/edit", methods=["GET", "POST"])
@require_auth
def edit_gist(gist_id):
    """
    Edit a gist; only the owner may do so.
    """
    storage = get_storage()
    result = storage.retrieve(GIST_NAMESPACE, f"{gist_id}.json")
    if result is None:
        abort(404)
    gist, etag = result

    user = get_current_user()
    if gist["created_by"] != user:
        abort(403)

    if request.method == "GET":
        return render_template("edit.html", gist=gist, gist_id=gist_id)

    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()

    if not content:
        return render_template(
            "edit.html", gist=gist, gist_id=gist_id, error="Content is required."
        )

    now = int(time.time())
    updated = {
        **gist,
        "title": title or "Untitled",
        "content": content,
        "updated_at": now,
        "hide_email": bool(request.form.get("hide_email")),
    }
    try:
        storage.store(GIST_NAMESPACE, f"{gist_id}.json", updated, version=etag)
    except StorageConflictError:
        return render_template(
            "edit.html",
            gist=gist,
            gist_id=gist_id,
            error="This gist was modified by another session. Please reload and try again.",
        )
    _update_user_index(
        storage,
        user,
        gist_id,
        updated["title"],
        gist["created_at"],
        action="update_title",
    )

    return redirect(f"/{gist_id}")


@app.route("/<gist_id>/delete", methods=["POST"])
@require_auth
def delete_gist(gist_id):
    """
    Delete a gist; only the owner may do so.
    """
    storage = get_storage()
    result = storage.retrieve(GIST_NAMESPACE, f"{gist_id}.json")
    if result is None:
        abort(404)
    gist, _ = result

    user = get_current_user()
    if gist["created_by"] != user:
        abort(403)

    storage.delete(GIST_NAMESPACE, f"{gist_id}.json")
    _update_user_index(storage, user, gist_id, None, None, action="remove")

    return redirect("/")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
