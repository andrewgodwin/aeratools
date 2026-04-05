import json
import os
from collections import defaultdict

from authentication import register_auth_context
from flask import Flask, render_template

app = Flask(__name__)
ROOT_DOMAIN = os.environ.get("ROOT_DOMAIN", "")
register_auth_context(app)

with open("tools.json") as f:
    _tools_raw = json.load(f)

# Pre-group tools, sorting groups and tools within each group alphabetically
_groups = defaultdict(list)
for key, tool in _tools_raw.items():
    if tool.get("group") == "__hidden__":
        continue
    _groups[tool.get("group", "Other")].append({**tool, "key": key})
GROUPS = {
    group: sorted(tools, key=lambda t: t.get("name", t["key"]))
    for group, tools in sorted(_groups.items())
}


@app.route("/")
def index():
    return render_template("index.html", groups=GROUPS, root_domain=ROOT_DOMAIN)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80)
