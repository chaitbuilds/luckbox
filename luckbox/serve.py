"""A small local page for the brief: the moves, their links, and one-click marks.

Bound to 127.0.0.1 only. Marks are POSTs carrying a per-install token, and the Host header must be
local, so other websites can't mark on your behalf."""
import datetime
import html
import http.server
import os
import secrets
import urllib.parse

from . import config, ledger

PORT = 8765
CSS = """
:root { --bg:#fff; --fg:#111; --muted:#777; --faint:#bbb; --line:#efefef; --hover:#f7f7f7; }
@media (prefers-color-scheme: dark) { :root { --bg:#111; --fg:#ececec; --muted:#8d8d8d; --faint:#555; --line:#1f1f1f; --hover:#181818; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.45 -apple-system, BlinkMacSystemFont, sans-serif;
  -webkit-font-smoothing: antialiased; }
main { max-width: 640px; margin: 0 auto; padding: 36px 16px 96px; }
header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 20px; }
h1 { font-size: 15px; font-weight: 600; margin: 0; }
.count, .keys { color: var(--muted); font-size: 13px; }
h2 { font-size: 11px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin: 26px 0 2px; }
ol { list-style: none; margin: 0; padding: 0; }
li { border-bottom: 1px solid var(--line); }
.line { display: flex; gap: 12px; align-items: baseline; padding: 9px 8px; margin: 0 -8px; cursor: pointer; border-radius: 6px; }
.line:hover, li.focus .line { background: var(--hover); }
.h { flex: 1; }
.tag { color: var(--muted); font-size: 13px; white-space: nowrap; }
.new { color: var(--bg); background: var(--fg); font-size: 10px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  padding: 1px 5px; border-radius: 4px; align-self: center; }
.you { color: var(--fg); font-size: 13px; white-space: nowrap; }
li.marked .h, li.marked .tag { color: var(--faint); }
.more { display: none; padding: 2px 0 12px; font-size: 14px; color: var(--muted); }
li.open .more { display: block; }
.more p { margin: 0 0 6px; }
.meta { display: flex; gap: 14px; align-items: center; font-size: 13px; }
.meta a { color: var(--fg); text-decoration: none; }
form { display: inline-flex; gap: 12px; margin-left: auto; }
button { font: inherit; background: none; border: 0; padding: 0; color: var(--faint); cursor: pointer; }
button:hover { color: var(--fg); }
button.on { color: var(--fg); font-weight: 600; }
.empty { color: var(--muted); }
nav { margin-top: 36px; font-size: 13px; color: var(--muted); }
nav a { color: var(--muted); margin-right: 12px; text-decoration: none; }
"""

JS = """
const items = [...document.querySelectorAll('li')]; let i = items.findIndex(li => !li.classList.contains('marked'));
function focus(n) { if (!items.length) return; items.forEach(li => li.classList.remove('focus'));
  i = Math.max(0, Math.min(items.length - 1, n)); items[i].classList.add('focus'); items[i].scrollIntoView({block: 'nearest'}); }
async function mark(li, m) { const f = li.querySelector('form'); const d = new URLSearchParams(new FormData(f)); d.set('mark', m);
  const r = await fetch('/mark', {method: 'POST', body: d, headers: {'X-Luckbox': '1'}}); if (!r.ok) return;
  f.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.value === m));
  if (m === 'good') return; li.classList.add('marked'); setTimeout(() => { li.style.display = 'none'; }, 600); count(); }
function count() { const left = items.filter(li => !li.classList.contains('marked')).length;
  const n = items.filter(li => li.querySelector('.new') && !li.classList.contains('marked')).length;
  document.querySelector('.count').textContent = `${n} new · ${left} on your list`; }
items.forEach((li, n) => li.querySelector('.line').addEventListener('click', () => { focus(n); li.classList.toggle('open'); }));
document.querySelectorAll('form').forEach(f => f.addEventListener('submit', e => { e.preventDefault(); mark(f.closest('li'), e.submitter.value); }));
const keys = {g: 'good', d: 'done', r: 'replied', x: 'weak', w: 'weak'};
document.addEventListener('keydown', e => { if (e.metaKey || e.ctrlKey || e.altKey) return; const li = items[i];
  if (e.key === 'j') focus(i + 1); else if (e.key === 'k') focus(i - 1);
  else if ((e.key === ' ' || e.key === 'Enter') && li) { e.preventDefault(); li.classList.toggle('open'); }
  else if (e.key === 'o' && li) window.open(li.querySelector('.meta a').href, '_blank');
  else if (keys[e.key] && li) { mark(li, keys[e.key]); focus(i + 1); } });
if (items.length) focus(0);
"""


import base64 as _b64
FAVICON = "data:image/png;base64," + _b64.b64encode(open(os.path.join(os.path.dirname(__file__), "favicon.png"), "rb").read()).decode()

SHORT = {"researchseminars.org": "talk", "OpenAlex": "paper", "arXiv": "paper", "Hacker News": "HN",
         "People": "update", "Events scout": "event"}


def token():
    p = config.path("serve.token")
    if not os.path.exists(p):
        config.write_private(p, secrets.token_urlsafe(24))
    return open(p).read().strip()


def _titles():
    from . import radar
    rs = radar.load_all()
    return {r["name"]: (r.get("title") or r["name"], -r.get("weight", 1.0)) for r in rs}


def _who_you_know(rows):
    """Facts, not the judge: which known people or LinkedIn connections appear in each item."""
    from . import brief, store
    from .identity import name_key
    known = brief.known_names()
    try:  # LinkedIn is large, so it matches on full first and last name, not initials
        li = {name_key(r["name"]): r["name"] for r in
              store.connect().execute("SELECT name FROM linkedin WHERE person_id IS NULL").fetchall() if name_key(r["name"])}
    except Exception:
        li = {}
    out = {}
    for r in rows:
        import re
        chunks = re.split(r"[,;·]|\band\b|\(|\)|:", f"{r['authors']}, {r['snippet']}")
        hits = []
        for c in chunks:
            c = c.strip()
            if not 1 < len(c.split()) <= 5:
                continue
            k = brief._initial_key(c)
            if k and k in known:
                hits.append(c)
            elif name_key(c) and name_key(c) in li:
                hits.append(f"{li[name_key(c)]} (LinkedIn)")
        out[r["id"]] = sorted(set(hits))[:3]
    return out


LABELS = (("good", "keep"), ("done", "done"), ("replied", "replied"), ("weak", "✕"))


def _row(r, tok, knows, today):
    e = html.escape
    known = knows.get(r["item"]) or []
    you = f"<span class=you>● {e(known[0].split(' (')[0].split()[-1])}</span>" if known else ""
    tag = f"<span class=tag>{e(SHORT.get(r['source'], r['kind']))}</span>" if r["kind"] in ("paper", "post", "update") else ""
    new = "<span class=new>new</span>" if r["day"] == today else ""
    headline = r["headline"] or (r["move"][:70] + ("…" if len(r["move"]) > 70 else ""))
    marks = "".join(f"<button name=mark value={m}{' class=on' if r['mark'] == m else ''}>{label}</button>" for m, label in LABELS)
    return (f"<li data-mark='{r['mark'] or ''}'><div class=line>{new}<span class=h>{e(headline)}</span>{you}{tag}</div>"
            f"<div class=more><p>{e(r['why'])}</p><p>{e(r['move'])}</p>"
            f"<div class=meta><a href='{e(r['url'])}' target=_blank rel=noopener>Open {e(r['source'])} ↗</a>"
            + (f"<span>you know {e(', '.join(known))}</span>" if known else "") +
            f"<form method=post action=/mark><input type=hidden name=token value='{tok}'>"
            f"<input type=hidden name=sid value='{r['id']}'>{marks}</form></div></div></li>")


def page():
    from . import brief
    con = ledger.connect()
    today = datetime.date.today()
    rows = brief.open_moves(con, today)
    titles, knows, tok = _titles(), _who_you_know(rows), token()
    new = sum(1 for r in rows if r["day"] == today.isoformat())
    out = ["<!doctype html><html lang=en><head><meta charset=utf-8>"
           "<meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<title>luckbox</title><link rel=icon href='{FAVICON}'><style>{CSS}</style></head><body><main>",
           f"<header><h1>{html.escape(today.strftime('%A, %B %-d'))}</h1>"
           f"<span class=count>{new} new · {len(rows)} on your list</span></header>"]
    if not rows:
        out.append("<p class=empty>Your list is clear.</p>")
    groups = {}
    for r in rows:
        groups.setdefault(r["radar"], []).append(r)
    for name in sorted(groups, key=lambda n: titles.get(n, (n, 0))[1]):
        out.append(f"<h2>{html.escape(titles.get(name, (name,))[0])}</h2><ol>")
        out += [_row(r, tok, knows, today.isoformat()) for r in groups[name]]
        out.append("</ol>")
    out.append("<nav><span class=keys>j / k move · space details · o open · g keep · d done · r replied · x dismiss</span>"
               "<br><br><a href='/cleared'>cleared</a></nav>"
               f"<script>{JS}</script></main></body></html>")
    return "".join(out)


def cleared_page():
    con = ledger.connect()
    rows = con.execute("SELECT s.*, i.radar FROM suggestion s JOIN item i ON i.id = s.item_id"
                       " WHERE s.mark IN ('done', 'replied', 'weak') ORDER BY s.marked_at DESC LIMIT 200").fetchall()
    e = html.escape
    out = ["<!doctype html><html lang=en><head><meta charset=utf-8>"
           "<meta name=viewport content='width=device-width,initial-scale=1'>"
           f"<title>luckbox: cleared</title><link rel=icon href='{FAVICON}'><style>{CSS}</style></head><body><main>",
           "<header><h1>Cleared</h1><a class=count href='/'>back to your list</a></header><ol>"]
    for r in rows:
        label = dict(LABELS).get(r["mark"], r["mark"])
        out.append(f"<li><div class=line><span class=h>{e(r['headline'] or r['move'][:70])}</span>"
                   f"<span class=tag>{e(label)} · {e((r['marked_at'] or '')[:10])}</span></div></li>")
    out.append("</ol></main></body></html>")
    return "".join(out)


class Handler(http.server.BaseHTTPRequestHandler):
    def _local(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        return host in ("127.0.0.1", "localhost") and (
            origin is None or urllib.parse.urlparse(origin).hostname in ("127.0.0.1", "localhost"))

    def _send(self, code, body="", ctype="text/html; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        if not self._local():
            return self._send(403, "forbidden")
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            return self._send(200, page())
        if u.path == "/cleared":
            return self._send(200, cleared_page())
        self._send(404, "not found")

    def do_POST(self):
        if not self._local() or self.path != "/mark":
            return self._send(403, "forbidden")
        n = int(self.headers.get("Content-Length") or 0)
        f = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(min(n, 4096)).decode()).items()}
        from . import marks
        if not secrets.compare_digest(f.get("token", ""), token()) or f.get("mark") not in marks.MARKS:
            return self._send(403, "forbidden")
        try:
            marks.apply_id(int(f.get("sid", 0)), f["mark"])
        except ValueError:
            return self._send(400, "bad mark")
        if self.headers.get("X-Luckbox"):
            return self._send(204)
        self._send(303, headers={"Location": "/"})

    def log_message(self, *a):
        pass


def url(cfg=None):
    port = ((cfg or {}).get("serve") or {}).get("port", PORT)
    return f"http://127.0.0.1:{port}/"


def run(port=PORT):
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
