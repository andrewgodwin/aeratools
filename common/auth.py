import os
import time

import jwt
from flask import request, redirect


COOKIE_NAME = "aeratools_session"
SESSION_DURATION = 30 * 24 * 3600  # 30 days


def _secret():
    return os.environ.get("SESSION_SECRET", "")


def get_current_user(req=None):
    """Return the signed-in email from the session cookie, or None."""
    secret = _secret()
    if not secret:
        return None
    if req is None:
        req = request
    token = req.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("email")
    except jwt.PyJWTError:
        return None


def make_session_token(email):
    """Create a signed JWT for the given email."""
    now = int(time.time())
    return jwt.encode(
        {"email": email, "iat": now, "exp": now + SESSION_DURATION},
        _secret(),
        algorithm="HS256",
    )


def set_session_cookie(response, email, root_domain):
    """Attach the session cookie to a response."""
    response.set_cookie(
        COOKIE_NAME,
        make_session_token(email),
        max_age=SESSION_DURATION,
        httponly=True,
        secure=bool(root_domain),
        samesite="Lax",
        domain=f".{root_domain}" if root_domain else None,
    )
    return response


def clear_session_cookie(response, root_domain):
    """Remove the session cookie from a response."""
    response.delete_cookie(
        COOKIE_NAME,
        domain=f".{root_domain}" if root_domain else None,
    )
    return response


def register_auth_context(app):
    """Inject `user` and `auth_url` into every template rendered by app."""
    @app.context_processor
    def _inject():
        root_domain = os.environ.get("ROOT_DOMAIN", "")
        return {
            "user": get_current_user(),
            "auth_url": f"https://auth.{root_domain}" if root_domain else "",
        }


def require_auth(f):
    """Route decorator: redirects unauthenticated requests to the auth tool."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_user():
            root_domain = os.environ.get("ROOT_DOMAIN", "")
            auth_base = f"https://auth.{root_domain}" if root_domain else "/auth"
            return redirect(f"{auth_base}/?next={request.url}")
        return f(*args, **kwargs)

    return decorated
