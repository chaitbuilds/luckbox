"""The telling half of luck (doing x telling). From what you've actually been doing (recent commits in
the repos you list, plus your profile) and what people are talking about right now, draft a few post
ideas. It never posts anything."""
import datetime
import hashlib
import json
import os
import subprocess
import urllib.parse

from .. import config
from ..judge import claude_bin, parse_array
from . import context_text, get

PROMPT = """Today is {today}. Draft at most {n} post ideas for the person in CONTEXT, for their own channel.

Luck is doing times telling: good posts show something real they made or learned, with a specific angle,
tied to something people are already talking about this week. A post may connect the work to a trend
even when the link is loose, as long as the connection is honest and interesting.

WHAT THEY'VE BEEN DOING (recent commits):
{work}

WHAT PEOPLE ARE TALKING ABOUT NOW:
{trending}

Rules:
- Never use anything under a heading containing "Private" in CONTEXT, nor an employer's internal work.
- Each idea needs something concrete to show: a clip, a screenshot, a number, a before/after.
- No generic takes, no threads about productivity, no hype.

Return ONLY a JSON array, no prose:
[{{"headline": "<8 words>", "hook": "<first line of the post>", "angle": "<one sentence>",
  "show": "<what to attach>", "trend": "<which trend it rides, or empty>", "trend_url": "", "why_now": "<one sentence>"}}]

<CONTEXT>
{context}
</CONTEXT>"""


def work(repos, days):
    lines = []
    for path in repos:
        path = os.path.expanduser(path)
        try:
            log = subprocess.run(["git", "-C", path, "log", f"--since={days} days ago", "--no-merges", "--pretty=%s"],
                                 capture_output=True, text=True, timeout=20).stdout.split("\n")
        except Exception:
            continue
        subjects = [s for s in log if s.strip()][:25]
        if subjects:
            lines.append(f"- {os.path.basename(path)} ({len(subjects)} commits): " + "; ".join(subjects))
    return "\n".join(lines)


def trending(n=30):
    url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({"tags": "front_page", "hitsPerPage": n})
    hits = json.loads(get(url)).get("hits", [])
    return [(h.get("title") or "", h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
             h.get("points") or 0) for h in hits]


def run(src, radar):
    cfg = config.load()
    doing = work(src.get("repos", []), src.get("days", 14))
    if not doing:
        return [], 0.0
    trends = trending(src.get("trending", 30))
    prompt = PROMPT.format(today=datetime.date.today().isoformat(), n=src.get("ideas", 3), work=doing,
                           trending="\n".join(f"- {t} ({p} points) {u}" for t, u, p in trends),
                           context=context_text(radar, cfg))
    cmd = [claude_bin(cfg), "-p", "--output-format", "json", "--no-session-persistence", "--safe-mode",
           "--tools", "", "--max-turns", "1"]
    if (cfg.get("claude") or {}).get("model"):
        cmd += ["--model", cfg["claude"]["model"]]
    data = json.loads(subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600).stdout)
    if data.get("is_error"):
        raise RuntimeError(str(data.get("result"))[:300])
    out = []
    for r in parse_array(data.get("result") or ""):
        head = (r.get("headline") or "").strip()
        if not head:
            continue
        out.append({
            "id": "idea:" + hashlib.sha1(head.lower().encode()).hexdigest()[:12], "source": "Telling", "kind": "idea",
            "title": head[:300], "url": r.get("trend_url") or "", "authors": "",
            "published": datetime.date.today().isoformat(),
            "snippet": " · ".join(x for x in [f"hook: {r.get('hook', '')}", f"angle: {r.get('angle', '')}",
                                               f"show: {r.get('show', '')}", f"rides: {r.get('trend', '')}",
                                               f"why now: {r.get('why_now', '')}"] if x.split(": ", 1)[1]),
        })
    return out, float(data.get("total_cost_usd") or 0)
