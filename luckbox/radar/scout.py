"""A web scout for events that can't be read directly (pages behind bot checks, scattered calls
for applications). Headless Claude with only web search and fetch, run every few days, returning
facts as JSON. Every URL is checked; the judge still decides what matters."""
import datetime
import json
import urllib.error
import urllib.request

from .. import config
from ..judge import claude_bin, parse_array
from . import UA, context_text

PROMPT = """You are an events scout. Today is {today}. Find real opportunities to meet researchers or join
programs in the areas described in CONTEXT:
- talks, seminars, colloquia and workshops in the next {days} days at the places below;
- schools, programs and calls for applications or abstracts with deadlines in the next {deadline_days} days, anywhere.

Look first at: {places}

{extra}

Rules:
- List only items you saw on a web page during this session, with that page's URL.
- Never guess a date. If a date is unclear, leave it empty.
- Skip anything CONTEXT lists as a near miss, and anything outside its areas.
- At most {max_items} items, most relevant first.

Return ONLY a JSON array, no prose:
[{{"title": "", "kind": "talk|seminar|workshop|school|conference|call", "start": "YYYY-MM-DD or empty",
  "deadline": "YYYY-MM-DD or empty", "location": "", "speaker": "", "url": "", "note": "<=25 words"}}]

<CONTEXT>
{context}
</CONTEXT>"""


PEOPLE_PROMPT = """You are checking what is publicly new with a few people. Today is {today}. For each person below,
search the web for things from the last {days} days: a new job or role, a launch, funding, a paper, a talk, an
award, a move, a post where they ask for something or say what they need. The detail after each name tells you
which person it is; if you can't be confident a result is about that person, leave it out.

{people}

Rules:
- Only report what you saw on a web page during this session, with that page's URL and its date.
- Nothing older than {days} days. Nothing private or personal (health, family, relationships).
- If nothing is new for someone, report nothing for them.

Return ONLY a JSON array, no prose:
[{{"person": "", "what": "<one line, what changed>", "date": "YYYY-MM-DD or empty", "url": "", "note": "<=25 words"}}]"""


def run_people(src, radar):
    """Public updates on people you know, anchored so namesakes stay out. Family and work are skipped."""
    import subprocess
    from .. import people
    cfg = config.load()
    skip = set(src.get("skip_labels", ["family", "macro"]))
    anchors = src.get("anchors", {})
    lines = []
    for p in people.core():
        if p["label"] in skip:
            continue
        a = anchors.get(p["name"]) or people.anchor(p)
        if a:
            lines.append(f"- {p['name']} ({a})")
    out, cost, rows = [], 0.0, []
    size = src.get("batch", 4)  # a few people per call: one call for eight ran out of steps and found nothing
    for k in range(0, len(lines), size):
        prompt = PEOPLE_PROMPT.format(today=datetime.date.today().isoformat(), days=src.get("days", 30),
                                      people="\n".join(lines[k:k + size]))
        cmd = [claude_bin(cfg), "-p", "--output-format", "json", "--no-session-persistence", "--safe-mode",
               "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch",
               "--max-turns", str(src.get("max_turns", 60)), "--max-budget-usd", str(src.get("budget_usd", 2))]
        if (cfg.get("claude") or {}).get("model"):
            cmd += ["--model", cfg["claude"]["model"]]
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=src.get("timeout", 1800))
        data = json.loads(p.stdout)
        cost += float(data.get("total_cost_usd") or 0)
        if data.get("is_error"):
            continue
        try:
            rows += parse_array(data.get("result") or "")
        except ValueError:
            continue
    for r in rows:
        url, who, what = (r.get("url") or "").strip(), (r.get("person") or "").strip(), (r.get("what") or "").strip()
        if not url.startswith("http") or not who or not what or _check(url) == "missing":
            continue
        out.append({
            "id": f"update:{who}:{url}", "source": "People", "kind": "update", "title": f"{who}: {what}"[:300],
            "url": url, "authors": who, "published": r.get("date") or datetime.date.today().isoformat(),
            "snippet": _clean_note(r.get("note")),
        })
    return out, cost


def _clean_note(s):
    return (s or "").strip()[:300]


def _check(url):
    """'ok', 'blocked' (exists but refuses bots) or 'missing'."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="GET")
        with urllib.request.urlopen(req, timeout=20) as r:
            return "ok" if r.status < 400 else "missing"
    except urllib.error.HTTPError as e:
        return "missing" if e.code in (404, 410) else "blocked"
    except Exception:
        return "blocked"


def run(src, radar):
    import subprocess
    cfg = config.load()
    prompt = PROMPT.format(today=datetime.date.today().isoformat(), days=src.get("days_ahead", 45),
                           deadline_days=src.get("deadline_days", 120), places=src.get("places", ""),
                           extra=src.get("brief", ""), max_items=src.get("max_items", 25),
                           context=context_text({"context": src.get("context", radar.get("context", []))}, cfg))
    cmd = [claude_bin(cfg), "-p", "--output-format", "json", "--no-session-persistence", "--safe-mode",
           "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch",
           "--max-turns", str(src.get("max_turns", 40)), "--max-budget-usd", str(src.get("budget_usd", 3))]
    model = (cfg.get("claude") or {}).get("model")
    if model:
        cmd += ["--model", model]
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=src.get("timeout", 1800))
    data = json.loads(p.stdout)
    if data.get("is_error"):
        raise RuntimeError(str(data.get("result"))[:300])
    rows = parse_array(data.get("result") or "")
    out = []
    for r in rows:
        url, title = (r.get("url") or "").strip(), (r.get("title") or "").strip()
        if not url.startswith("http") or not title:
            continue
        status = _check(url)
        if status == "missing":
            continue
        when = r.get("start") or ""
        deadline = r.get("deadline") or ""
        out.append({
            # Dates are part of the id, so an item comes back for judging once its deadline is posted.
            "id": f"scout:{url}#{title[:60]}#{when}#{deadline}", "source": src.get("label", "Web scout"), "kind": "event",
            "title": title[:300], "url": url, "authors": (r.get("speaker") or "")[:300],
            "published": when or deadline or datetime.date.today().isoformat(),
            "snippet": " · ".join(x for x in [r.get("kind", ""), f"starts {when}" if when else "",
                                               f"deadline {deadline}" if deadline else "", r.get("location", ""),
                                               r.get("note", ""), "" if status == "ok" else "[page blocks bots: verify]"] if x),
        })
    return out, float(data.get("total_cost_usd") or 0)
