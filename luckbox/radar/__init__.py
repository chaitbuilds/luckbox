"""Radars watch the outside world. A radar is a JSON file in LUCKBOX_HOME/radars/: which context
files describe what matters, and which sources to watch. Sources return items (facts only); the
judge decides what they mean."""
import json
import os
import urllib.request

from .. import config

UA = "luckbox/0.1 (+https://github.com/chaitbuilds/luckbox)"


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def load_all():
    d = config.path("radars")
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".json"):
            with open(os.path.join(d, f)) as fh:
                r = json.load(fh)
            r.setdefault("name", f[:-5])
            out.append(r)
    return out


def context_text(radar, cfg):
    """Concatenate the radar's context files. 'profile:x' is relative to the profile repo,
    'local:x' to LUCKBOX_HOME (for anything that must never be in git), and 'people:core' is the
    list of people you know with how you know them and when you last spoke."""
    parts = []
    for ref in radar.get("context", []):
        kind, _, rel = ref.partition(":")
        if kind == "people":
            from .. import people
            parts.append(f"<file name=\"people\">\n{people.summary()}\n</file>")
            continue
        base = cfg["profile"] if kind == "profile" else config.home()
        p = os.path.join(base, rel)
        if os.path.exists(p):
            parts.append(f"<file name=\"{rel}\">\n{open(p).read().strip()}\n</file>")
    return "\n\n".join(parts)
