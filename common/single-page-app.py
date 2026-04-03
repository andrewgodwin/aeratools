import os

from flask import Flask, render_template

app = Flask(__name__)
app.config["ROOT_DOMAIN"] = os.environ.get("ROOT_DOMAIN", "")


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
