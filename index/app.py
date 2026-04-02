import json
import os
from collections import defaultdict
from flask import Flask, render_template

app = Flask(__name__)
ROOT_DOMAIN = os.environ.get("ROOT_DOMAIN", "")

with open("tools.json") as f:
    _tools_raw = json.load(f)

# Pre-group tools preserving insertion order within each group
_groups = defaultdict(list)
for key, tool in _tools_raw.items():
    if tool.get("group") == "hidden":
        continue
    _groups[tool.get("group", "Other")].append({**tool, "key": key})
GROUPS = dict(_groups)


@app.route("/")
def index():
    return render_template("index.html", groups=GROUPS, root_domain=ROOT_DOMAIN)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
