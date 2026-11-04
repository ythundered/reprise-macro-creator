import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    r = json.load(f)
bad = []
if not r["frozen"]:
    bad.append("not a frozen build")
if not r["svg"]:
    bad.append("svg plugin missing")
if not r["icon"]:
    bad.append("icon did not load")
if "reprise macro creator" not in r["title"]:
    bad.append("wrong window title")
if sys.platform.startswith("linux"):
    if not any("wayland" in p for p in r["platforms"]):
        bad.append("wayland plugin missing")
    for name, t in r["tools"].items():
        if t["exit"] is None or "tools" not in (t["path"] or ""):
            bad.append(f"bundled {name} not used: {t}")
if bad:
    sys.exit("\n".join(bad))
print("ok")
