"""
Flask app for the filedrop tool: upload files and share temporary download links.
"""

import os
import time
import uuid
from datetime import datetime, timezone

from authentication import get_current_user, register_auth_context, require_auth
from flask import (
    Flask,
    Response,
    abort,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from storage import StorageConflictError, get_storage

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")
app.config["MAX_CONTENT_LENGTH"] = (
    int(os.environ.get("MAX_UPLOAD_MB", 1000)) * 1024 * 1024
)
register_auth_context(app)

FILES_NAMESPACE = "__filedrop__"
BIN_PREFIX = "bin"

TTL_OPTIONS = [
    ("3600", "1 hour"),
    ("86400", "24 hours"),
    ("604800", "7 days"),
    ("2592000", "30 days"),
]


@app.template_filter("filesizeformat")
def filesizeformat(value):
    """
    Format a byte count as a human-readable file size string.
    """
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


@app.template_filter("datetimeformat")
def datetimeformat(value):
    """
    Format a Unix timestamp as a human-readable UTC date/time string.
    """
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _prune_expired(storage, user):
    """
    Remove expired files from the user's index and delete their stored data.
    """
    now = int(time.time())
    for _ in range(5):
        result = storage.retrieve(user, "filedrop_index.json")
        if result is None:
            return
        index, etag = result
        expired = [f for f in index.get("files", []) if f["expires_at"] <= now]
        if not expired:
            return
        for f in expired:
            storage.delete(FILES_NAMESPACE, f"{f['id']}.json")
            storage.delete(FILES_NAMESPACE, f"{BIN_PREFIX}/{f['id']}")
        index["files"] = [f for f in index.get("files", []) if f["expires_at"] > now]
        try:
            storage.store(user, "filedrop_index.json", index, version=etag)
            return
        except StorageConflictError:
            continue
    storage.store(user, "filedrop_index.json", index)


def _update_user_index(storage, user, file_id, summary, action):
    """
    Update the user's file index with retry logic for optimistic concurrency conflicts.
    """
    for _ in range(5):
        result = storage.retrieve(user, "filedrop_index.json")
        if result is None:
            index, etag = {"files": []}, None
        else:
            index, etag = result
        if action == "add":
            index["files"].insert(0, summary)
        elif action == "remove":
            index["files"] = [f for f in index.get("files", []) if f["id"] != file_id]
        try:
            storage.store(user, "filedrop_index.json", index, version=etag)
            return
        except StorageConflictError:
            continue
    storage.store(user, "filedrop_index.json", index)


@app.route("/")
def index():
    """
    Home page: upload form and file listing for logged-in users, login prompt otherwise.
    """
    user = get_current_user()
    files = []
    uploaded_url = None
    uploaded_name = None
    if user:
        storage = get_storage()
        _prune_expired(storage, user)
        result = storage.retrieve(user, "filedrop_index.json")
        if result:
            files = result[0].get("files", [])
        uploaded_id = request.args.get("uploaded")
        if uploaded_id:
            meta_result = storage.retrieve(FILES_NAMESPACE, f"{uploaded_id}.json")
            if meta_result:
                meta = meta_result[0]
                uploaded_url = url_for("download", file_id=uploaded_id, _external=True)
                uploaded_name = meta["name"]
    return render_template(
        "index.html",
        files=files,
        ttl_options=TTL_OPTIONS,
        uploaded_url=uploaded_url,
        uploaded_name=uploaded_name,
    )


@app.route("/upload", methods=["POST"])
@require_auth
def upload():
    """
    Handle file upload: store binary data and metadata, update the user's index.
    """
    file = request.files.get("file")
    if not file or not file.filename:
        return redirect("/")

    ttl_str = request.form.get("ttl", "86400")
    valid_ttls = {t for t, _ in TTL_OPTIONS}
    ttl = int(ttl_str) if ttl_str in valid_ttls else 86400

    user = get_current_user()
    storage = get_storage()
    file_id = uuid.uuid4().hex
    now = int(time.time())
    content_type = file.content_type or "application/octet-stream"

    class _CountingStream:
        """
        Wraps a file-like stream and tracks the total number of bytes read.
        """

        def __init__(self, stream):
            self.stream = stream
            self.size = 0

        def read(self, size=-1):
            """
            Read from the wrapped stream and accumulate byte count.
            """
            data = self.stream.read(size)
            self.size += len(data)
            return data

    counting = _CountingStream(file.stream)
    storage.store_bytes(
        FILES_NAMESPACE, f"{BIN_PREFIX}/{file_id}", counting, content_type
    )

    metadata = {
        "id": file_id,
        "owner": user,
        "name": file.filename,
        "size": counting.size,
        "content_type": content_type,
        "uploaded_at": now,
        "expires_at": now + ttl,
    }
    storage.store(FILES_NAMESPACE, f"{file_id}.json", metadata)

    summary = {
        "id": file_id,
        "name": file.filename,
        "size": counting.size,
        "expires_at": now + ttl,
    }
    _update_user_index(storage, user, file_id, summary, action="add")

    return redirect(f"/?uploaded={file_id}")


@app.route("/f/<file_id>")
def download(file_id):
    """
    Public download endpoint: stream the file if it exists and hasn't expired.
    """
    storage = get_storage()
    result = storage.retrieve(FILES_NAMESPACE, f"{file_id}.json")
    if result is None:
        abort(404)
    metadata, _ = result

    if int(time.time()) > metadata["expires_at"]:
        abort(410)

    stream = storage.retrieve_bytes(FILES_NAMESPACE, f"{BIN_PREFIX}/{file_id}")
    if stream is None:
        abort(404)

    filename = metadata["name"]
    content_type = metadata.get("content_type", "application/octet-stream")

    def generate():
        """
        Yield file content in 1 MB chunks, closing the stream when done.
        """
        try:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            stream.close()

    return Response(
        stream_with_context(generate()),
        content_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(metadata["size"]),
        },
    )


@app.route("/delete/<file_id>", methods=["POST"])
@require_auth
def delete(file_id):
    """
    Delete a file; only the owner may do so.
    """
    storage = get_storage()
    result = storage.retrieve(FILES_NAMESPACE, f"{file_id}.json")
    if result is None:
        abort(404)
    metadata, _ = result

    user = get_current_user()
    if metadata["owner"] != user:
        abort(403)

    storage.delete(FILES_NAMESPACE, f"{BIN_PREFIX}/{file_id}")
    storage.delete(FILES_NAMESPACE, f"{file_id}.json")
    _update_user_index(storage, user, file_id, None, action="remove")

    return redirect("/")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
