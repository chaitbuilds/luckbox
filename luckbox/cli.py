"""luckbox command line.

  python3 -m luckbox init               first-run setup: config, folders, a profile from the template
  python3 -m luckbox radar draft FILE   have Claude draft a radar from an interest file

  python3 -m luckbox ingest             rebuild people.db from every source in config.json
  python3 -m luckbox status             counts by decision
  python3 -m luckbox snapshot SOURCE    reduce a mail archive to a small contacts file
  python3 -m luckbox review             write review/people.md listing people with no decision yet
  python3 -m luckbox decide WHO DECISION [LABEL] [NOTE]
                                        WHO is an email or a name; DECISION is inner|keep|nosuggest|drop
  python3 -m luckbox lookup TEXT        who do I know at a company, or in a role
  python3 -m luckbox show NAME          everything held on one person

  python3 -m luckbox fetch              pull new items for every radar
  python3 -m luckbox judge              judge every new item against the radar's context
  python3 -m luckbox brief              write today's brief (picks once per day)
  python3 -m luckbox daily              fetch, judge, brief, notify: what launchd runs
  python3 -m luckbox mark N good|weak|done|replied [NOTE]   done/replied also record the contact
  python3 -m luckbox scoreboard         how the suggestions have landed
  python3 -m luckbox serve              the brief page at http://127.0.0.1:8765/
  python3 -m luckbox schedule [--hour H --minute M | --off]   daily run + always-on page via launchd (macOS)
"""
import argparse
import collections
import datetime
import json
import sys

from . import brief as brief_mod, config, identity, judge as judge_mod, ledger, radar, serve as serve_mod, store
from .radar import sources as radar_sources
from .sources import READERS, linkedin


def ingest(args):
    cfg = config.load()
    excl, dec = identity.Exclusions.load(), identity.Decisions.load()
    con, tmp = store.fresh()
    by_handle, by_key = {}, {}
    tally = collections.Counter()

    def person_for(c):
        for e in c["emails"]:
            if e in by_handle:
                return by_handle[e]
        k = identity.name_key(c["name"])
        if k and k in by_key:
            return by_key[k]
        d = dec.lookup(c["name"], c["emails"]) or {}
        cur = con.execute(
            "INSERT INTO person (key, name, decision, label, note) VALUES (?,?,?,?,?)",
            (k or c["emails"][0], c["name"] or c["emails"][0], d.get("decision"), d.get("label"), d.get("note")))
        if k:
            by_key[k] = cur.lastrowid
        return cur.lastrowid

    for src in cfg.get("sources", []):
        if src["type"] == "linkedin":
            continue
        found = READERS[src["type"]](src, cfg["me"])
        for c in found:
            if excl.match(c["name"], c["emails"]):
                tally["excluded"] += 1
                continue
            d = dec.lookup(c["name"], c["emails"])
            if d and d["decision"] == "drop":
                tally["dropped"] += 1
                continue
            pid = person_for(c)
            for e in c["emails"]:
                by_handle[e] = pid
                con.execute("INSERT OR IGNORE INTO handle VALUES (?, 'email', ?)", (pid, e))
            con.execute(
                "INSERT OR REPLACE INTO interaction VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, src["name"], c["you_sent"], c["they_sent"], c["meetings"], c["first"], c["last"],
                 json.dumps(c["subjects"]), c["context"]))
        print(f"  {src['name']:<10} {len(found):>5} two-way contacts")

    for src in cfg.get("sources", []):
        if src["type"] != "linkedin":
            continue
        rows = linkedin.read(src)
        for r in rows:
            if excl.match(r["name"], [r["email"]] if r["email"] else []):
                tally["excluded"] += 1
                continue
            k = identity.name_key(r["name"])
            con.execute(
                "INSERT INTO linkedin (person_id, key, name, email, company, position, connected_on, url, invite_note)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (by_key.get(k), k, r["name"], r["email"], r["company"], r["position"], r["connected_on"], r["url"],
                 r["invite_note"]))
        print(f"  {src['name']:<10} {len(rows):>5} connections (lookup only)")

    # People you decided to keep who appear in no source (e.g. met through a luckbox move).
    for d in list(dec.by_name.values()):
        k = identity.name_key(d["email"])
        if d["decision"] != "drop" and k and k not in by_key:
            cur = con.execute("INSERT INTO person (key, name, decision, label, note) VALUES (?,?,?,?,?)",
                              (k, d["email"].strip(), d["decision"], d.get("label"), d.get("note")))
            by_key[k] = cur.lastrowid
            con.execute("UPDATE linkedin SET person_id = ? WHERE key = ? AND person_id IS NULL", (cur.lastrowid, k))
    store.commit(con, tmp)
    _status(tally)


def _status(tally=None):
    con = store.connect()
    counts = dict(con.execute("SELECT COALESCE(decision, 'undecided'), COUNT(*) FROM person GROUP BY 1").fetchall())
    li = con.execute("SELECT COUNT(*), COUNT(person_id) FROM linkedin").fetchone()
    order = ["inner", "keep", "nosuggest", "undecided"]
    print("people:  " + "  ".join(f"{k} {counts.get(k, 0)}" for k in order))
    print(f"linkedin: {li[0]} connections, {li[1]} matched to a person")
    if tally:
        print(f"skipped: {tally['dropped']} dropped by decision, {tally['excluded']} excluded")


def snapshot(args):
    """Reduce a mail source to a small contacts CSV (headers-derived facts only), so the archive can go."""
    import csv
    import io
    cfg = config.load()
    src = next((x for x in cfg["sources"] if x["name"] == args.source), None)
    if not src or src["type"] != "mbox":
        sys.exit(f"no mbox source named {args.source}")
    rows = READERS["mbox"](src, cfg["me"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "email", "company", "internal", "you_sent", "they_sent", "meetings", "first", "last", "context", "subjects"])
    for c in rows:
        w.writerow([c["name"], ";".join(c["emails"]), "", "", c["you_sent"], c["they_sent"], 0, c["first"], c["last"], "",
                    " | ".join(c["subjects"])])
    out = config.path("snapshots", f"{args.source}.csv")
    config.write_private(out, buf.getvalue())
    print(f"{len(rows)} contacts -> {out}. Point the source at it with type contacts_csv; the archive is then unused.")


def status(args):
    _status()


def review(args):
    con = store.connect()
    rows = con.execute(
        "SELECT p.id, p.name, GROUP_CONCAT(DISTINCT h.value) emails FROM person p"
        " LEFT JOIN handle h ON h.person_id = p.id WHERE p.decision IS NULL GROUP BY p.id ORDER BY p.name").fetchall()
    lines = [f"# luckbox review, {datetime.date.today().isoformat()}", "",
             "People with no decision yet. Headers only; no message bodies were read.", "",
             "Decide with `python3 -m luckbox decide <email> inner|keep|nosuggest|drop`.", ""]
    for r in rows:
        inter = con.execute("SELECT * FROM interaction WHERE person_id = ?", (r["id"],)).fetchall()
        li = con.execute("SELECT company, position FROM linkedin WHERE person_id = ?", (r["id"],)).fetchone()
        lines.append(f"## {r['name']}  <{r['emails']}>")
        for i in inter:
            subj = "; ".join(json.loads(i["subjects"] or "[]")[:3])
            lines.append(f"- {i['source']}: you {i['you_sent']} / them {i['they_sent']}, {i['first']} to {i['last']}"
                         + (f". {i['context']}" if i["context"] else "") + (f". Subjects: {subj}" if subj else ""))
        if li:
            lines.append(f"- LinkedIn: {li['position']} @ {li['company']}")
        lines.append("")
    out = config.path("review", "people.md")
    config.write_private(out, "\n".join(lines) + "\n")
    print(f"{len(rows)} undecided -> {out}")


def decide(args):
    identity.record(args.who, args.decision, args.label or "", args.note or "")
    print(f"{args.who}: {args.decision}. Run ingest to apply.")


def lookup(args):
    con = store.connect()
    q = f"%{args.text.lower()}%"
    people = con.execute(
        "SELECT DISTINCT p.name, p.decision, l.position, l.company FROM person p LEFT JOIN linkedin l ON l.person_id = p.id"
        " LEFT JOIN interaction i ON i.person_id = p.id"
        " WHERE p.decision IN ('inner','keep','nosuggest') AND (lower(p.name) LIKE ? OR lower(l.company) LIKE ?"
        " OR lower(l.position) LIKE ? OR lower(i.context) LIKE ? OR lower(p.label) LIKE ? OR lower(p.note) LIKE ?)",
        (q,) * 6).fetchall()
    conns = con.execute(
        "SELECT name, position, company FROM linkedin WHERE person_id IS NULL AND"
        " (lower(company) LIKE ? OR lower(position) LIKE ? OR lower(name) LIKE ?) ORDER BY company, name",
        (q,) * 3).fetchall()
    for r in people:
        print(f"[{r['decision']}] {r['name']}" + (f": {r['position']} @ {r['company']}" if r["company"] else ""))
    for r in conns[: args.limit]:
        print(f"[linkedin] {r['name']}: {r['position']} @ {r['company']}")
    if len(conns) > args.limit:
        print(f"... {len(conns) - args.limit} more LinkedIn connections (--limit)")
    if not people and not conns:
        print("nobody")


def show(args):
    con = store.connect()
    k = identity.name_key(args.name)
    rows = con.execute("SELECT * FROM person WHERE key = ? OR lower(name) LIKE ?",
                       (k, f"%{args.name.lower()}%")).fetchall()
    if not rows:
        print("nobody by that name")
    for p in rows:
        print(f"{p['name']}  [{p['decision'] or 'undecided'}]" + (f"  {p['label']}" if p["label"] else "")
              + (f": {p['note']}" if p["note"] else ""))
        for h in con.execute("SELECT value FROM handle WHERE person_id = ?", (p["id"],)):
            print(f"  email     {h['value']}")
        for i in con.execute("SELECT * FROM interaction WHERE person_id = ?", (p["id"],)):
            print(f"  {i['source']:<9} you {i['you_sent']} / them {i['they_sent']} / meetings {i['meetings']},"
                  f" {i['first']} to {i['last']}" + (f"  ({i['context']})" if i["context"] else ""))
            for s in json.loads(i["subjects"] or "[]"):
                print(f"            · {s}")
        for l in con.execute("SELECT * FROM linkedin WHERE person_id = ?", (p["id"],)):
            print(f"  linkedin  {l['position']} @ {l['company']}  {l['url']}")


def _radars(args):
    only = getattr(args, "radar", None)
    return [r for r in radar.load_all() if not only or r["name"] == only]


BACKFILL = 4  # a radar's first fetch looks this many times further back, so day one isn't empty


def first_fetch_window(src):
    """Widen look-back windows for a brand-new radar."""
    src = dict(src)
    if "days" in src and src["type"] in ("arxiv", "hn", "rss", "openalex"):
        src["days"] = src["days"] * BACKFILL
    elif src["type"] in ("arxiv", "hn", "rss", "openalex"):
        src["days"] = {"arxiv": 7, "hn": 3, "rss": 10, "openalex": 30}[src["type"]] * BACKFILL
    return src


def fetch(args):
    con = ledger.connect()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for r in _radars(args):
        new = seen = 0
        first = not con.execute("SELECT 1 FROM item WHERE radar = ? LIMIT 1", (r["name"],)).fetchone()
        for src in r.get("sources", []):
            if first:
                src = first_fetch_window(src)
            label = src.get("label") or src["type"]
            try:
                if src["type"] in ("scout", "people_scout", "telling"):
                    step = f"scout:{r['name']}:{label}"
                    last = con.execute("SELECT MAX(started) FROM run WHERE step = ?", (step,)).fetchone()[0]
                    due = (datetime.datetime.now() - datetime.timedelta(days=src.get("every_days", 7))).isoformat()
                    if last and last > due and not getattr(args, "force_scouts", False):
                        continue
                    from .radar import scout, telling
                    runner = {"scout": scout.run, "people_scout": scout.run_people, "telling": telling.run}[src["type"]]
                    items, cost = runner(src, r)
                    con.execute("INSERT INTO run (started, step, detail, cost_usd) VALUES (?,?,?,?)",
                                (now, step, f"{len(items)} items", cost))
                    print(f"  {r['name']}: {label} found {len(items)} (${cost:.2f})")
                else:
                    items = radar_sources.READERS[src["type"]](src)
            except Exception as e:
                print(f"  {r['name']}: {src.get('label') or src['type']} failed: {e}")
                continue
            for it in items:
                other = con.execute("SELECT radar FROM item WHERE id = ?", (it["id"],)).fetchone()
                if other and other["radar"] != r["name"]:
                    if it["kind"] == "paper":
                        seen += 1
                        continue
                    it["id"] = f"{r['name']}~{it['id']}"  # an event can matter to two radars for different reasons
                tk = ledger.title_key(it["title"])
                if it["kind"] == "paper" and tk and con.execute(
                        "SELECT 1 FROM item WHERE title_key = ? AND id != ?", (tk, it["id"])).fetchone():
                    seen += 1
                    continue
                cur = con.execute(
                    "INSERT OR IGNORE INTO item (id, radar, source, kind, title, url, authors, published, snippet,"
                    " fetched_at, title_key) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (it["id"], r["name"], it["source"], it["kind"], it["title"], it["url"], it["authors"],
                     it["published"], it["snippet"], now, tk))
                new += cur.rowcount
                seen += 1
        con.commit()
        print(f"  {r['name']}: {seen} seen, {new} new")


def judge(args):
    cfg, con = config.load(), ledger.connect()
    for r in _radars(args):
        n, passed, failed, cost = judge_mod.run(con, cfg, r, radar.context_text(r, cfg), limit=args.limit)
        print(f"  {r['name']}: judged {n}, passed {passed}, failed {failed}, ${cost:.2f}")


def brief(args, notify=False):
    con = ledger.connect()
    today = datetime.date.today()
    rows = brief_mod.make(con, radar.load_all(), today)
    print(brief_mod.render(con, rows, today))
    if notify:
        brief_mod.notify(rows, serve_mod.url(config.load()), len(brief_mod.open_moves(con, today)))


def _trim_logs(limit=1_000_000):
    import os
    for name in ("daily.log", "daily.err", "serve.log", "serve.err"):
        p = config.path("logs", name)
        if os.path.exists(p) and os.path.getsize(p) > limit:
            with open(p, "rb") as f:
                f.seek(-limit // 2, 2)
                tail = f.read()
            with open(p, "wb") as f:
                f.write(tail)


def daily(args):
    print(f"luckbox daily {datetime.datetime.now().isoformat(timespec='seconds')}")
    ingest(args)  # picks up people added by yesterday's marks
    fetch(args)
    judge(args)
    brief(args, notify=True)
    print(f"  pruned {ledger.prune(ledger.connect())} old unsuggested items")
    _trim_logs()


def mark(args):
    from . import marks
    day = args.day or datetime.date.today().isoformat()
    ok = marks.apply(day, args.n, args.mark, args.note or "")
    print(f"{day} #{args.n}: {args.mark}" if ok else f"no suggestion #{args.n} on {day}")


def scoreboard(args):
    con = ledger.connect()
    for r in con.execute(
            "SELECT i.radar, i.source, COUNT(*) n, SUM(s.mark = 'good') good, SUM(s.mark = 'done') done,"
            " SUM(s.mark = 'weak') weak, SUM(s.mark = 'replied') replied, SUM(s.mark IS NULL) unmarked FROM suggestion s JOIN item i ON i.id = s.item_id"
            " GROUP BY 1, 2 ORDER BY 1, n DESC"):
        print(f"  {r['radar']:<14} {r['source']:<20} {r['n']:>3} suggested  good {r['good'] or 0}  done {r['done'] or 0}"
              f"  weak {r['weak'] or 0}  replied {r['replied'] or 0}  unmarked {r['unmarked'] or 0}")
    j = con.execute("SELECT COUNT(*) n, SUM(pass) p FROM judgment WHERE error IS NULL").fetchone()
    c = con.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM run").fetchone()[0]
    print(f"  judged {j['n']}, passed {j['p'] or 0}; judge cost to date ${c:.2f}")


PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{python}</string><string>-m</string><string>luckbox</string><string>daily</string></array>
  <key>WorkingDirectory</key><string>{repo}</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>{hour}</integer><key>Minute</key><integer>{minute}</integer></dict>
  <key>StandardOutPath</key><string>{logs}/daily.log</string>
  <key>StandardErrorPath</key><string>{logs}/daily.err</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>{home}/.local/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    <key>HOME</key><string>{home}</string>
    <key>LUCKBOX_HOME</key><string>{luckbox_home}</string>
  </dict>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
"""


SERVE_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{python}</string><string>-m</string><string>luckbox</string><string>serve</string></array>
  <key>WorkingDirectory</key><string>{repo}</string>
  <key>StandardOutPath</key><string>{logs}/serve.log</string>
  <key>StandardErrorPath</key><string>{logs}/serve.err</string>
  <key>EnvironmentVariables</key>
  <dict><key>HOME</key><string>{home}</string><key>LUCKBOX_HOME</key><string>{luckbox_home}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
"""


CRON_TAG = "# luckbox"


def _schedule_cron(args, repo, logs):
    """Linux and other Unix: two crontab lines, tagged so they can be replaced or removed."""
    import subprocess
    current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout.splitlines()
    lines = [l for l in current if CRON_TAG not in l]
    if not args.off:
        env = f"cd {repo} && LUCKBOX_HOME={config.home()} {sys.executable} -m luckbox"
        lines += [f"{args.minute} {args.hour} * * * {env} daily >> {logs}/daily.log 2>&1 {CRON_TAG}",
                  f"@reboot {env} serve >> {logs}/serve.log 2>&1 {CRON_TAG}"]
    subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True)
    if not args.off:
        subprocess.Popen([sys.executable, "-m", "luckbox", "serve"], cwd=repo, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("schedule removed" if args.off else f"cron: daily at {args.hour:02d}:{args.minute:02d}; page at {serve_mod.url(config.load())}")


def schedule(args):
    """Install (or replace) the daily run and the always-on brief page: launchd on macOS, cron elsewhere."""
    import os
    import subprocess
    if sys.platform != "darwin":
        logs = config.path("logs")
        os.makedirs(logs, exist_ok=True)
        return _schedule_cron(args, os.path.dirname(os.path.dirname(os.path.abspath(__file__))), logs)
    logs = config.path("logs")
    os.makedirs(logs, exist_ok=True)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    domain = f"gui/{os.getuid()}"
    fields = dict(python=sys.executable, repo=repo, hour=args.hour, minute=args.minute, logs=logs,
                  home=os.path.expanduser("~"), luckbox_home=config.home())
    for label, template in (("com.luckbox.daily", PLIST), ("com.luckbox.serve", SERVE_PLIST)):
        plist = os.path.expanduser(f"~/Library/LaunchAgents/{label}.plist")
        subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
        if args.off:
            if os.path.exists(plist):
                os.remove(plist)
            continue
        with open(plist, "w") as f:
            f.write(template.format(label=label, **fields))
        r = subprocess.run(["launchctl", "bootstrap", domain, plist], capture_output=True, text=True)
        if r.returncode:
            print(f"{label}: launchctl failed: {r.stderr.strip()}")
        elif label == "com.luckbox.serve":
            subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{label}"], capture_output=True)
    print("schedule removed" if args.off else
          f"daily at {args.hour:02d}:{args.minute:02d}; brief page at {serve_mod.url(config.load())}")


def serve(args):
    serve_mod.run(((config.load().get("serve") or {}).get("port")) or serve_mod.PORT)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="luckbox", description="Local-first engine for luck surface area.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    from . import setup as setup_mod
    it = sub.add_parser("init", help="first-run setup")
    it.add_argument("--force", action="store_true")
    it.set_defaults(fn=setup_mod.init)
    rd = sub.add_parser("radar", help="radar tools")
    rsub = rd.add_subparsers(dest="radar_cmd", required=True)
    dr = rsub.add_parser("draft", help="draft a radar from an interest file")
    dr.add_argument("interest")
    dr.add_argument("--name")
    dr.set_defaults(fn=setup_mod.draft)
    sub.add_parser("ingest").set_defaults(fn=ingest)
    sub.add_parser("status").set_defaults(fn=status)
    sn = sub.add_parser("snapshot")
    sn.add_argument("source")
    sn.set_defaults(fn=snapshot)
    sub.add_parser("review").set_defaults(fn=review)
    d = sub.add_parser("decide")
    d.add_argument("who")
    d.add_argument("decision", choices=identity.DECISIONS)
    d.add_argument("label", nargs="?")
    d.add_argument("note", nargs="?")
    d.set_defaults(fn=decide)
    lk = sub.add_parser("lookup")
    lk.add_argument("text")
    lk.add_argument("--limit", type=int, default=25)
    lk.set_defaults(fn=lookup)
    s = sub.add_parser("show")
    s.add_argument("name")
    s.set_defaults(fn=show)
    ft = sub.add_parser("fetch")
    ft.add_argument("--force-scouts", action="store_true")
    ft.add_argument("--radar", help="only this radar")
    ft.set_defaults(fn=fetch)
    jg = sub.add_parser("judge")
    jg.add_argument("--limit", type=int, default=200)
    jg.add_argument("--radar", help="only this radar")
    jg.set_defaults(fn=judge)
    sub.add_parser("brief").set_defaults(fn=brief)
    dl = sub.add_parser("daily")
    dl.add_argument("--limit", type=int, default=200)
    dl.set_defaults(fn=daily)
    mk = sub.add_parser("mark")
    mk.add_argument("n", type=int)
    mk.add_argument("mark", choices=("good", "weak", "done", "replied"))
    mk.add_argument("note", nargs="?")
    mk.add_argument("--day")
    mk.set_defaults(fn=mark)
    sub.add_parser("scoreboard").set_defaults(fn=scoreboard)
    sub.add_parser("serve").set_defaults(fn=serve)
    sc = sub.add_parser("schedule")
    sc.add_argument("--hour", type=int, default=6)
    sc.add_argument("--minute", type=int, default=30)
    sc.add_argument("--off", action="store_true")
    sc.set_defaults(fn=schedule)
    args = ap.parse_args(argv)
    try:
        args.fn(args)
    except FileNotFoundError as e:
        sys.exit(f"luckbox: {e.filename} not found. Is LUCKBOX_HOME set up? (default ~/.luckbox)")
