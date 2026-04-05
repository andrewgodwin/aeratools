import os

from authentication import register_auth_context
from flask import Flask, render_template

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")
register_auth_context(app)


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
