"""The daily brief: the few best moves not yet suggested, each with why it matters to you."""
import datetime
import os
import subprocess

from . import config

NOTIFIER = "~/Applications/Luckbox.app/Contents/MacOS/Luckbox"


KNOWN_BONUS = 0.15  # an item involving someone you know outranks an equal one that doesn't


def _initial_key(name):
    """'Ada B. Lovelace' and 'Ada Lovelace' -> 'a lovelace'; 'Charlie' and 'Charles' Babbage agree too."""
    from .identity import name_key
    k = name_key(name)
    return f"{k[0]} {k.split()[-1]}" if k else ""


def known_names():
    from . import store
    try:
        rows = store.connect().execute("SELECT name FROM person WHERE decision IN ('inner','keep')").fetchall()
    except Exception:
        return set()
    return {_initial_key(r["name"]) for r in rows} - {""}


def involves_known(row, names):
    """Facts only: does a known person's name appear among the item's authors, hosts or guests?"""
    import re
    chunks = re.split(r"[,;·]|\band\b|\(|\)|:", f"{row['authors']}, {row['snippet']}")
    return any(_initial_key(c.strip()) in names for c in chunks if 1 < len(c.split()) <= 5)


def select(con, radars, today, limit=5):
    picks = []
    names = known_names()
    for radar in radars:
        if radar.get("every_days"):
            last = con.execute("SELECT MAX(s.day) FROM suggestion s JOIN item i ON i.id = s.item_id WHERE i.radar = ?",
                               (radar["name"],)).fetchone()[0]
            if last and last > (today - datetime.timedelta(days=radar["every_days"])).isoformat():
                continue
        rows = con.execute(
            "SELECT i.*, j.score, j.headline, j.move, j.why, j.person FROM item i JOIN judgment j ON j.item_id = i.id"
            " WHERE i.radar = ? AND j.pass = 1 AND j.score >= MIN(?, ?)"
            " AND i.id NOT IN (SELECT item_id FROM suggestion)"
            " AND (i.published = '' OR i.published >= ?)"
            " AND (COALESCE(i.kind, '') != 'event' OR i.published >= ?) ORDER BY j.score DESC",
            (radar["name"], radar.get("min_score", 0.6), min([radar.get("min_score", 0.6)] + list(radar.get("min_score_by_kind", {}).values())),
             (today - datetime.timedelta(days=radar.get("fresh_days", 14))).isoformat(), today.isoformat())).fetchall()
        floor = radar.get("min_score_by_kind", {})
        rows = [r for r in rows if r["score"] >= floor.get(r["kind"] or "", radar.get("min_score", 0.6))]
        rows = sorted(rows, key=lambda r: -(r["score"] + (KNOWN_BONUS if involves_known(r, names) else 0)))
        per_source, per_kind, chosen = {}, {}, []
        kind_caps = radar.get("max_per_kind", {})
        for r in rows:
            kind = r["kind"] or ""
            if per_source.get(r["source"], 0) >= radar.get("max_per_source", 2):
                continue
            if kind in kind_caps and per_kind.get(kind, 0) >= kind_caps[kind]:
                continue
            per_source[r["source"]] = per_source.get(r["source"], 0) + 1
            per_kind[kind] = per_kind.get(kind, 0) + 1
            chosen.append(r)
            if len(chosen) >= radar.get("max_per_day", 5):
                break
        picks += [(radar.get("weight", 1.0) * (r["score"] + (KNOWN_BONUS if involves_known(r, names) else 0)),
                   radar["name"], r) for r in chosen]
    # A radar's weight reorders across radars (e.g. physics first); it never lets a weak item in.
    return [(name, r) for _, name, r in sorted(picks, key=lambda p: -p[0])[:limit]]


def make(con, radars, today, limit=None):
    """Today's brief. Picking happens once per day; later runs re-render the same picks."""
    if limit is None:
        try:
            limit = (config.load().get("brief") or {}).get("max", 5)
        except FileNotFoundError:
            limit = 5
    day = today.isoformat()
    rows = con.execute("SELECT s.*, i.radar, i.source FROM suggestion s JOIN item i ON i.id = s.item_id"
                       " WHERE s.day = ? ORDER BY s.rank", (day,)).fetchall()
    if not rows:
        for n, (radar, r) in enumerate(select(con, radars, today, limit), 1):
            con.execute("INSERT INTO suggestion (item_id, day, rank, headline, move, why, url) VALUES (?,?,?,?,?,?,?)",
                        (r["id"], day, n, r["headline"], r["move"], r["why"], r["url"]))
        con.commit()
        rows = con.execute("SELECT s.*, i.radar, i.source FROM suggestion s JOIN item i ON i.id = s.item_id"
                           " WHERE s.day = ? ORDER BY s.rank", (day,)).fetchall()
    return rows


def render(con, rows, today):
    day = today.isoformat()
    lines = [f"# luckbox, {day}", ""]
    if not rows:
        lines.append("Nothing worth your time today.")
    for r in rows:
        mark = f"  [{r['mark']}]" if r["mark"] else ""
        lines += [f"**{r['rank']}. {r['headline'] or r['move']}**{mark}", f"{r['move']} {r['why']}",
                  f"{r['url']}  ·  _{r['radar']}, {r['source']}_", ""]
    if rows:
        lines += ["---", "Mark each: `python3 -m luckbox mark <n> good|weak|done|replied [note]`"]
    text = "\n".join(lines) + "\n"
    config.write_private(config.path("out", f"{day}.md"), text)
    config.write_private(config.path("out", "today.md"), text)
    return text


def notify(rows, url, open_count=None):
    """Click opens the brief page. Falls back to a plain notification without Luckbox.app."""
    if not rows:
        return
    title = f"{len(rows)} new" + (f" · {open_count} on your list" if open_count else "")
    body = " · ".join((r["headline"] or r["move"][:60]) for r in rows[:3])[:200]
    app = os.path.expanduser(NOTIFIER)
    if os.path.exists(app):
        r = subprocess.run([app, "post", title, body, url], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return
    import shutil
    import sys
    if sys.platform != "darwin":
        if shutil.which("notify-send"):
            subprocess.run(["notify-send", f"luckbox: {title}", f"{body}\n{url}"], capture_output=True, timeout=10)
        return
    safe = body.replace("\\", "").replace('"', "'")
    subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "luckbox: {title}"'],
                   capture_output=True, timeout=10)


def open_moves(con, today, stale_days=10, keep_days=45):
    """Your running list. A move stays until you clear it (done, replied, dismiss), except: events
    leave once they've happened, untouched moves after stale_days, kept (good) moves after keep_days."""
    return con.execute(
        "SELECT s.*, i.radar, i.source, i.kind, i.published, i.authors, i.snippet, i.id AS item"
        " FROM suggestion s JOIN item i ON i.id = s.item_id"
        " WHERE (s.mark IS NULL OR s.mark = 'good')"
        " AND NOT (i.kind = 'event' AND i.published < ?)"
        " AND NOT (s.mark IS NULL AND s.day < ?)"
        " AND NOT (s.mark = 'good' AND s.day < ?)"
        " ORDER BY s.day DESC, s.rank",
        (today.isoformat(), (today - datetime.timedelta(days=stale_days)).isoformat(),
         (today - datetime.timedelta(days=keep_days)).isoformat())).fetchall()
