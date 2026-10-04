"""First-run setup and radar drafting, so someone else can get from clone to a first brief."""
import json
import os
import shutil
import subprocess
import urllib.error

from . import config
from .judge import claude_bin, parse_array
from .radar import get

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ask(prompt, default=""):
    try:
        got = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    except EOFError:
        got = ""
    return got or default


def _system_timezone():
    import re
    try:
        m = re.search(r"zoneinfo[^/]*/(.+)$", os.readlink("/etc/localtime"))
        return m.group(1) if m else "UTC"
    except OSError:
        return "UTC"


def init(args):
    home = config.home()
    if os.path.exists(os.path.join(home, "config.json")) and not args.force:
        print(f"{home}/config.json already exists. Nothing changed (use --force to redo the questions).")
        return
    print("luckbox setup. Everything personal stays in", home, "and your profile folder.\n")
    name = _ask("Your name")
    emails = [e.strip() for e in _ask("Your email addresses, comma separated (so your own mail isn't a contact)").split(",") if e.strip()]
    city = _ask("Your city, as people write it (e.g. New York, London)")
    cities = [c.strip().lower() for c in _ask("Names that count as nearby, comma separated", city).split(",") if c.strip()]
    tz = _ask("Your timezone", _system_timezone())
    profile = os.path.expanduser(_ask("Where to keep your profile (markdown about you; make it a private git repo)",
                                      "~/luckbox-profile"))
    for d in ("", "people", "radars", "archives", "logs", "context"):
        os.makedirs(os.path.join(home, d), exist_ok=True)
    os.chmod(home, 0o700)
    cfg = {"profile": profile, "me": emails, "home": {"timezone": tz, "cities": cities},
           "claude": {"model": "claude-sonnet-5-5", "escalate_model": "claude-opus-5-5"},
           "brief": {"max": 15}, "sources": []}
    config.write_private(config.path("config.json"), json.dumps(cfg, indent=2))
    for rel, text in (("exclude.txt", "# Never index: one name, email, phone or handle per line.\n"),
                      ("people/decisions.tsv", "# email\tdecision\tlabel\tnote\n"),
                      ("people/routers.md", "# Routers\n\nPeople close to you who can open a world. Name, the world they "
                                            "reach, and the time they recommended you.\n")):
        if not os.path.exists(config.path(rel)):
            config.write_private(config.path(rel), text)
    if not os.path.exists(profile):
        shutil.copytree(os.path.join(REPO, "examples", "profile"), profile)
        me = os.path.join(profile, "me.md")
        text = open(me).read().replace("# Ada Example", f"# {name or 'You'}")
        open(me, "w").write(text)
    print(f"""
Done. Next:
  1. Edit {profile}/me.md and {profile}/interests/*.md: who you are, what you're after, what's private.
  2. Draft a radar for each interest:   python3 -m luckbox radar draft {profile}/interests/<file>.md
  3. Optional, people you know: add a Google Takeout mbox or LinkedIn export to config.json "sources",
     then: python3 -m luckbox ingest && python3 -m luckbox review
  4. First run:                         python3 -m luckbox daily
  5. Every morning, automatically:      python3 -m luckbox schedule
""")


SOURCES_DOC = """Source types you can use (JSON objects in "sources"):
- {"type": "arxiv", "query": "(cat:cs.HC) AND (abs:\\"phrase\\" OR abs:\\"phrase\\")", "days": 7, "max": 60}
- {"type": "hn", "queries": ["phrase", "phrase"], "days": 3, "min_points": 20}
- {"type": "rss", "label": "Name", "url": "..."}   any feed: a blog or Substack (/feed), a subreddit (https://www.reddit.com/r/NAME/top/.rss?t=week),
  a YouTube channel (https://www.youtube.com/feeds/videos.xml?channel_id=ID), a Google News search
  (https://news.google.com/rss/search?q=QUERY), GitHub releases (https://github.com/OWNER/REPO/releases.atom), a job board feed
- {"type": "openalex", "days": 45, "authors": [{"name": "Full Name", "hint": "Institution"}]}
- {"type": "seminars", "topics": ["cond-mat_stat-mech", "physics_bio-ph"], "days_ahead": 45}   (researchseminars.org topic codes)
- {"type": "luma", "categories": ["ai"], "calendars": ["calendar-slug"], "place": "city-slug", "days_ahead": 30}
- {"type": "page", "label": "Events page", "url": "https://...", "chars": 6000}   (a readable events page)
- {"type": "scout", "label": "Events scout", "every_days": 7, "places": "...", "brief": "..."}   (web search, for pages that block bots and for calls with deadlines)"""

DRAFT = """Draft a luckbox radar for the interest in INTEREST, for the person in PROFILE. A radar watches public sources
for moves worth this person's time: people to contact, events to attend, programs to apply to.

{doc}

Pick the source types that fit this interest; most interests aren't research, so use arXiv, OpenAlex and seminars only
when it is. Use web search to find real, current sources: feeds (blogs, newsletters, subreddits, YouTube, Google News
searches, job boards), Luma community calendars or the city page (public slug from the luma.com URL), readable events
pages, and, for research, the right arXiv categories and active researchers, near {city} where location matters.
Prefer a few high-signal sources over many.
Never put anything from a section headed "Private" into a query, label or URL.

Return ONLY a JSON object, no prose:
{{"name": "{name}", "title": "<2-3 words>", "weight": 1.0, "min_score": 0.6, "max_per_day": 5,
  "context": ["profile:me.md", "profile:now.md", "profile:{rel}"],
  "guidance": "<2-4 sentences: what a great move looks like for this interest, and what should fail>",
  "sources": [ ... ]}}

<PROFILE>
{me}
</PROFILE>

<INTEREST>
{interest}
</INTEREST>"""


def _reachable(url):
    try:
        get(url, timeout=20)
        return True
    except (urllib.error.URLError, ValueError, OSError):
        return False


def draft(args):
    from .radar.sources import READERS
    cfg = config.load()
    path = os.path.abspath(os.path.expanduser(args.interest))
    name = args.name or os.path.splitext(os.path.basename(path))[0]
    me_path = os.path.join(cfg["profile"], "me.md")
    rel = os.path.relpath(path, cfg["profile"]) if path.startswith(cfg["profile"]) else os.path.basename(path)
    prompt = DRAFT.format(doc=SOURCES_DOC, city=", ".join((cfg.get("home") or {}).get("cities", [])[:1]) or "them",
                          name=name, rel=rel, me=open(me_path).read() if os.path.exists(me_path) else "",
                          interest=open(path).read())
    cmd = [claude_bin(cfg), "-p", "--output-format", "json", "--no-session-persistence", "--safe-mode",
           "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch", "--max-turns", "40"]
    if (cfg.get("claude") or {}).get("model"):
        cmd += ["--model", cfg["claude"]["model"]]
    print("Drafting (a few minutes; it checks real sources)...")
    data = json.loads(subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=1800).stdout)
    text = (data.get("result") or "").strip()
    radar = json.loads(text[text.find("{"): text.rfind("}") + 1])
    kept = []
    for s in radar.get("sources", []):
        if s.get("type") not in READERS and s.get("type") not in ("scout", "people_scout", "telling"):
            print(f"  dropped unknown source type: {s.get('type')}")
        elif s.get("type") in ("rss", "page") and not _reachable(s.get("url", "")):
            print(f"  dropped unreachable {s['type']}: {s.get('url')}")
        else:
            kept.append(s)
    radar["sources"], radar["name"] = kept, name
    radar["context"] = ["profile:me.md", "profile:now.md", f"profile:{rel}"]  # never trust the model with file paths
    out = config.path("radars", f"{name}.json")
    config.write_private(out, json.dumps(radar, indent=2))
    print(f"\nWrote {out} with {len(kept)} sources:")
    for s in kept:
        print(f"  - {s['type']}: {s.get('label') or s.get('url') or s.get('query') or s.get('queries') or s.get('calendars') or ''}"[:110])
    print(f"\nReview it, then: python3 -m luckbox fetch --radar {name} && python3 -m luckbox judge --radar {name}")
