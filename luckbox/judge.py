"""The judge decides meaning. Headless `claude -p` with no tools and no ambient configuration,
batched, checkpointed after every batch, and parsed as JSON. Prose is never trusted as success."""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess

from . import config, store

RUBRIC = open(os.path.join(os.path.dirname(__file__), "judge.md")).read()
RUBRIC_VERSION = hashlib.sha1(RUBRIC.encode()).hexdigest()[:8]


def claude_bin(cfg):
    b = os.path.expanduser((cfg.get("claude") or {}).get("bin") or "")
    return b or shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")


def call(cfg, prompt, timeout=600):
    """Return (text, cost, error)."""
    cmd = [claude_bin(cfg), "-p", "--output-format", "json", "--no-session-persistence", "--safe-mode",
           "--tools", "", "--max-turns", "1",
           "--system-prompt", "You are a precise, skeptical judge. Output only what is asked."]
    model = (cfg.get("claude") or {}).get("model")
    if model:
        cmd += ["--model", model]
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", 0.0, f"timeout after {timeout}s"
    try:
        data = json.loads(p.stdout)
    except ValueError:
        return "", 0.0, f"unparseable output (exit {p.returncode}): {(p.stderr or p.stdout)[-500:]}"
    if data.get("is_error"):
        return "", float(data.get("total_cost_usd") or 0), f"claude error: {str(data.get('result'))[:500]}"
    return data.get("result") or "", float(data.get("total_cost_usd") or 0), ""


def parse_array(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S)
    i, j = text.find("["), text.rfind("]")
    try:
        rows = json.loads(text[i:j + 1]) if 0 <= i < j else None
    except ValueError:
        rows = None
    if not isinstance(rows, list):
        raise ValueError("no JSON array")
    return rows


def parse(text, ids):
    rows = parse_array(text)
    got = {str(r.get("id")): r for r in rows if isinstance(r, dict)}
    missing = [x for x in ids if x not in got]
    if missing:
        raise ValueError(f"missing ids: {missing[:3]}")
    return got


def known_people():
    try:
        con = store.connect()
        rows = con.execute("SELECT name, label FROM person WHERE decision IN ('inner','keep')").fetchall()
        return "\n".join(f"- {r['name']}" + (f" ({r['label']})" if r["label"] else "") for r in rows)
    except Exception:
        return ""


def recent_marks(con, radar_name, n=12):
    """Your latest marks on this radar's suggestions: the judge calibrates to them."""
    rows = con.execute("SELECT s.mark, s.move, s.note FROM suggestion s JOIN item i ON i.id = s.item_id"
                       " WHERE i.radar = ? AND s.mark IS NOT NULL ORDER BY s.marked_at DESC LIMIT ?", (radar_name, n))
    return "\n".join(f"- {r['mark']}: {r['move']}" + (f" (note: {r['note']})" if r["note"] else "") for r in rows)


def prompt_for(context, items, guidance="", marks=""):
    shown = [{k: it[k] for k in ("id", "source", "kind", "title", "authors", "published", "url", "snippet")}
             for it in items]
    extra = f"\n\n<RADAR_GUIDANCE>\n{guidance.strip()}\n</RADAR_GUIDANCE>" if guidance else ""
    if marks:
        extra += ("\n\n<YOUR_MARKS>\nHow you marked recent suggestions. good/done/replied: more like these. "
                  f"weak: fewer like these. Notes say why.\n{marks}\n</YOUR_MARKS>")
    return (f"{RUBRIC}{extra}\n\n<CONTEXT>\n{context}\n</CONTEXT>\n\n<KNOWN_PEOPLE>\n{known_people()}\n</KNOWN_PEOPLE>\n\n"
            f"<ITEMS>\n{json.dumps(shown, ensure_ascii=False, indent=1)}\n</ITEMS>")


def run(con, cfg, radar, context, batch=8, limit=200):
    """Judge every new item for this radar. Commits after each batch so a crash loses one batch at most.
    Items involving someone you know go to the stronger model (claude.escalate_model), the rest to claude.model."""
    from .brief import involves_known, known_names
    items = [dict(r) for r in con.execute(
        "SELECT * FROM item WHERE radar = ? AND status = 'new' ORDER BY published DESC LIMIT ?",
        (radar["name"], limit))]
    strong = (cfg.get("claude") or {}).get("escalate_model")
    names = known_names() if strong else set()
    known = [it for it in items if strong and involves_known(it, names)]
    rest = [it for it in items if it not in known]
    n1, p1, f1, c1 = _judge(con, dict(cfg, claude=dict(cfg.get("claude") or {}, model=strong)), radar, context, known, batch) \
        if known else (0, 0, 0, 0.0)
    n2, p2, f2, c2 = _judge(con, cfg, radar, context, rest, batch)
    return n1 + n2, p1 + p2, f1 + f2, c1 + c2


def _judge(con, cfg, radar, context, items, batch):
    total_cost, passed, failed = 0.0, 0, 0
    examples = recent_marks(con, radar["name"])
    for k in range(0, len(items), batch):
        chunk = items[k:k + batch]
        ids = [it["id"] for it in chunk]
        got, err = None, ""
        for _ in range(2):
            text, cost, err = call(cfg, prompt_for(context, chunk, radar.get("guidance", ""), examples))
            total_cost += cost
            if err:
                continue
            try:
                got = parse(text, ids)
                break
            except ValueError as e:
                err = f"parse: {e}"
        now = datetime.datetime.now().isoformat(timespec="seconds")
        for it in chunk:
            if got is None:
                con.execute("UPDATE item SET status = 'error' WHERE id = ?", (it["id"],))
                con.execute("INSERT OR REPLACE INTO judgment (item_id, judged_at, rubric, error) VALUES (?,?,?,?)",
                            (it["id"], now, RUBRIC_VERSION, err))
                failed += 1
                continue
            r = got[it["id"]]
            ok = bool(r.get("pass"))
            passed += ok
            con.execute(
                "INSERT OR REPLACE INTO judgment (item_id, pass, score, headline, move, why, person, judged_at, rubric)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (it["id"], int(ok), float(r.get("score") or 0), r.get("headline", ""), r.get("move", ""), r.get("why", ""),
                 r.get("person", ""), now, RUBRIC_VERSION))
            con.execute("UPDATE item SET status = 'judged' WHERE id = ?", (it["id"],))
        con.commit()
    if items:
        con.execute("INSERT INTO run (started, step, detail, cost_usd) VALUES (?,?,?,?)",
                    (datetime.datetime.now().isoformat(timespec="seconds"), f"judge:{radar['name']}",
                     f"{len(items)} judged, {passed} passed, {failed} failed, {(cfg.get('claude') or {}).get('model') or 'default'}",
                     total_cost))
        con.commit()
    return len(items), passed, failed, total_cost
