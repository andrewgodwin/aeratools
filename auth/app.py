import json
import os
import secrets
import smtplib
import time
from email.mime.text import MIMEText

import boto3
from flask import Flask, make_response, redirect, render_template, request

from auth import clear_session_cookie, get_current_user, register_auth_context, set_session_cookie

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")
register_auth_context(app)

TOKEN_TTL = 15 * 60  # 15 minutes
TOKEN_PREFIX = "auth/pending/"


def _s3():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def _send_email(to_addr, subject, body):
    from_addr = os.environ.get("EMAIL_FROM", f"noreply@{app.config['ROOT_DOMAIN']}")
    sendgrid_key = os.environ.get("SENDGRID_API_KEY")

    if sendgrid_key:
        import sendgrid
        from sendgrid.helpers.mail import Mail

        sg = sendgrid.SendGridAPIClient(sendgrid_key)
        sg.send(Mail(from_email=from_addr, to_emails=to_addr, subject=subject, plain_text_content=body))
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


@app.route("/")
def index():
    return render_template("index.html", next=request.args.get("next", ""))


@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email", "").strip().lower()
    next_url = request.form.get("next", "")

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return render_template("index.html", error="Please enter a valid email address.", next=next_url)

    token = secrets.token_urlsafe(32)
    bucket = os.environ.get("S3_BUCKET")
    _s3().put_object(
        Bucket=bucket,
        Key=f"{TOKEN_PREFIX}{token}.json",
        Body=json.dumps({"email": email, "expires": int(time.time()) + TOKEN_TTL, "next": next_url}),
        ContentType="application/json",
    )

    root_domain = app.config["ROOT_DOMAIN"]
    auth_base = f"https://auth.{root_domain}" if root_domain else request.host_url.rstrip("/")
    link = f"{auth_base}/verify?token={token}"

    _send_email(
        email,
        "Sign in to aeratools",
        f"Click this link to sign in (expires in 15 minutes):\n\n{link}\n\n"
        "If you didn't request this, you can safely ignore this email.",
    )

    return render_template("sent.html", email=email)


@app.route("/verify")
def verify():
    token = request.args.get("token", "")
    if not token:
        return redirect("/")

    bucket = os.environ.get("S3_BUCKET")
    key = f"{TOKEN_PREFIX}{token}.json"
    s3 = _s3()

    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        data = json.loads(obj["Body"].read())
    except Exception:
        return render_template("index.html", error="This sign-in link is invalid or has already been used.", next="")

    s3.delete_object(Bucket=bucket, Key=key)

    if int(time.time()) > data["expires"]:
        return render_template("index.html", error="This sign-in link has expired. Please request a new one.", next="")

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
