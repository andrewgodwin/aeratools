import os
import secrets
import smtplib
import sys
import time
from email.mime.text import MIMEText

from authentication import (
    clear_session_cookie,
    register_auth_context,
    set_session_cookie,
)
from flask import Flask, make_response, redirect, render_template, request
from storage import get_storage

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")
register_auth_context(app)

TOKEN_TTL = 15 * 60  # 15 minutes


def _send_email(to_addr, subject, body):
    if os.environ.get("EMAIL_DEBUG"):
        print(f"Email for {to_addr}:\n{body}", flush=True, file=sys.stderr)
        return
    from_addr = os.environ.get("EMAIL_FROM", f"noreply@{app.config['ROOT_DOMAIN']}")
    sendgrid_key = os.environ.get("SENDGRID_API_KEY")

    if sendgrid_key:
        import sendgrid
        from sendgrid.helpers.mail import Mail

        sg = sendgrid.SendGridAPIClient(sendgrid_key)
        sg.send(
            Mail(
                from_email=from_addr,
                to_emails=to_addr,
                subject=subject,
                plain_text_content=body,
            )
        )
    else:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        host = os.environ.get("SMTP_HOST", "localhost")
        port = int(os.environ.get("SMTP_PORT", 587))
        user = os.environ.get("SMTP_USER")
        password = os.environ.get("SMTP_PASS")
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            if user and password:
                server.login(user, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())


def _mask_email(email):
    local, domain = email.split("@", 1)
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * (len(local) - len(visible))}@{domain}"


@app.route("/")
def index():
    return render_template("index.html", next=request.args.get("next", ""))


@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email", "").strip().lower()
    next_url = request.form.get("next", "")

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return render_template(
            "index.html", error="Please enter a valid email address.", next=next_url
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    session_id = secrets.token_urlsafe(32)
    get_storage().store(
        session_id,
        "pending.json",
        {
            "email": email,
            "code": code,
            "expires": int(time.time()) + TOKEN_TTL,
            "next": next_url,
        },
    )

    _send_email(
        email,
        "Your aeratools sign-in code",
        f"Your sign-in code is: {code}\n\nIt expires in 15 minutes.\n\n"
        "If you didn't request this, you can safely ignore this email.",
    )

    return redirect(f"/verify?session={session_id}")


@app.route("/verify", methods=["GET", "POST"])
def verify():
    if request.method == "GET":
        session_id = request.args.get("session", "")
        if not session_id:
            return redirect("/")
        result = get_storage().retrieve(session_id, "pending.json")
        if result is None:
            return render_template(
                "index.html",
                error="This sign-in session is invalid or has expired.",
                next="",
            )
        data, _ = result
        if int(time.time()) > data["expires"]:
            get_storage().delete(session_id, "pending.json")
            return render_template(
                "index.html",
                error="This sign-in session has expired. Please try again.",
                next="",
            )
        return render_template(
            "verify.html",
            session_id=session_id,
            masked_email=_mask_email(data["email"]),
            next=data.get("next", ""),
        )

    # POST
    session_id = request.form.get("session", "")
    entered_code = request.form.get("code", "").strip()

    if not session_id:
        return redirect("/")

    storage = get_storage()
    result = storage.retrieve(session_id, "pending.json")

    if result is None:
        return render_template(
            "index.html",
            error="This sign-in session is invalid or has expired.",
            next="",
        )

    data, _ = result

    if int(time.time()) > data["expires"]:
        storage.delete(session_id, "pending.json")
        return render_template(
            "index.html",
            error="This sign-in session has expired. Please try again.",
            next="",
        )

    if not secrets.compare_digest(entered_code, data["code"]):
        return render_template(
            "verify.html",
            session_id=session_id,
            masked_email=_mask_email(data["email"]),
            next=data.get("next", ""),
            error="Incorrect code. Please try again.",
        )

    storage.delete(session_id, "pending.json")

    next_url = data.get("next") or "/"
    response = make_response(redirect(next_url))
    set_session_cookie(response, data["email"], app.config["ROOT_DOMAIN"])
    return response


@app.route("/logout")
def logout():
    response = make_response(redirect("/"))
    clear_session_cookie(response, app.config["ROOT_DOMAIN"])
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
