"""Assemble docs/walkthrough.html: theme kit (sliced by markers, delimiters stripped) + the page + walkthrough-data.json inline.
Run: python3 docs/build_walkthrough.py   (after docs/walkthrough_capture.py)"""
import json, pathlib, re, datetime
ROOT = pathlib.Path(__file__).parent.parent
KIT = pathlib.Path.home() / ".claude/reference/theme-kit/theme-kit.html"
k = KIT.read_text()
def slab(name, strip):
    m = re.search(rf"==KIT:{name}:START==(.*?)==KIT:{name}:END==", k, re.S); s = m.group(1)
    s = s.replace(strip, "", 1) if strip and s.lstrip().startswith(strip) else s
    i = s.rfind("<!--") if strip == "-->" else s.rfind("/*")
    if i != -1 and s[i:].strip() in ("<!--", "/*"): s = s[:i]
    return s.strip("\n")
CSS = slab("CSS", "*/"); CTL = slab("CONTROLS", "-->"); JS = slab("JS", "*/")
DATA = (ROOT / "docs" / "walkthrough-data.json").read_text()
PAGE = (ROOT / "docs" / "walkthrough.src.html").read_text()
origin = json.dumps({"cwd": "~/dev/guided-analytics-playground", "generator": "docs/build_walkthrough.py after docs/walkthrough_capture.py",
                     "prompt": "", "sources": ["server.py", "metrics.yaml", "prices.yaml", "data/northstar.duckdb", "evals/questions.json", "skill/shape-my-question/SKILL.md"],
                     "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "note": "guided walkthrough, every number from the server"})
# audit finding 6: a "</script>" inside captured text would close the tag, so "</" is escaped inside the JSON
html = (PAGE.replace("/*KIT_CSS*/", CSS).replace("<!--KIT_CONTROLS-->", CTL).replace("/*KIT_JS*/", JS)
        .replace("/*DATA*/", "const DATA=" + DATA.replace("</", "<\\/") + ";").replace("__ORIGIN__", origin.replace("'", "&#39;")))
(ROOT / "docs" / "walkthrough.html").write_text(html)
print("wrote docs/walkthrough.html", len(html), "bytes")
