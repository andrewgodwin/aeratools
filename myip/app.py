import os

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")


def get_ip_info():
    connecting_ip = request.remote_addr
    xff = request.headers.get("X-Forwarded-For", "").strip()
    x_real_ip = request.headers.get("X-Real-IP", "").strip()

    if xff:
        chain = [ip.strip() for ip in xff.split(",") if ip.strip()]
        client_ip = chain[0]
    elif x_real_ip:
        client_ip = x_real_ip
    else:
        client_ip = connecting_ip

    return {
        "ip": client_ip,
    }


@app.route("/")
def index():
    return render_template("index.html", **get_ip_info())


@app.route("/api/ip")
def api_ip():
    return jsonify(get_ip_info())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
