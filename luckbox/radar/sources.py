"""Source readers. Each returns items: dicts with id, source, kind, title, url, authors, published, snippet."""
import datetime
import hashlib
import html
import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from . import get
from .. import config

ATOM = "{http://www.w3.org/2005/Atom}"


def _clean(text, n=800):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:n]


def _since(days):
    return datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)


def _date(s):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=datetime.timezone.utc)


def hn(src):
    """Hacker News stories via the Algolia API: one search per query, recent and with some traction."""
    since = int(_since(src.get("days", 3)).timestamp())
    out = {}
    for q in src["queries"]:
        url = ("https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(
            {"query": q, "tags": "story", "numericFilters": f"created_at_i>{since},points>={src.get('min_points', 15)}",
             "hitsPerPage": 50}))
        for h in json.loads(get(url))["hits"]:
            out[h["objectID"]] = {
                "id": f"hn:{h['objectID']}", "source": "Hacker News", "kind": "post",
                "title": h.get("title") or "", "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                "authors": h.get("author") or "", "published": h.get("created_at", "")[:10],
                "snippet": _clean(h.get("story_text")) + f" [{h.get('points', 0)} points, {h.get('num_comments', 0)} comments,"
                           f" discussion https://news.ycombinator.com/item?id={h['objectID']}]",
            }
    return list(out.values())


_last_arxiv = [0.0]


def arxiv(src):
    """arXiv papers matching a search query, newest first, within the window."""
    import time
    time.sleep(max(0.0, 3.0 - (time.time() - _last_arxiv[0])))  # arXiv asks for 3s between calls
    _last_arxiv[0] = time.time()
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": src["query"], "sortBy": "submittedDate", "sortOrder": "descending",
         "max_results": src.get("max", 50)})
    since = _since(src.get("days", 7))
    out = []
    for e in ET.fromstring(get(url, timeout=60)).iter(ATOM + "entry"):
        published = _date(e.findtext(ATOM + "published"))
        if published and published < since:
            continue
        aid = (e.findtext(ATOM + "id") or "").rsplit("/", 1)[-1].split("v")[0]
        out.append({
            "id": f"arxiv:{aid}", "source": "arXiv", "kind": "paper",
            "title": _clean(e.findtext(ATOM + "title"), 300), "url": f"https://arxiv.org/abs/{aid}",
            "authors": ", ".join(a.findtext(ATOM + "name") or "" for a in e.iter(ATOM + "author"))[:300],
            "published": published.date().isoformat() if published else "",
            "snippet": _clean(e.findtext(ATOM + "summary")),
        })
    return out


def rss(src):
    """An RSS or Atom feed: the newest entries within the window."""
    root = ET.fromstring(get(src["url"]))
    since = _since(src.get("days", 10))
    out = []
    entries = list(root.iter("item")) or list(root.iter(ATOM + "entry"))
    for e in entries[: src.get("max", 10)]:
        link = e.findtext("link") or ""
        if not link:
            l = e.find(ATOM + "link")
            link = l.get("href", "") if l is not None else ""
        published = _date(e.findtext("pubDate") or e.findtext(ATOM + "published") or e.findtext(ATOM + "updated"))
        if published and published < since:
            continue
        body = (e.findtext("description") or e.findtext(ATOM + "summary") or e.findtext(ATOM + "content") or "")
        out.append({
            "id": f"rss:{e.findtext('guid') or e.findtext(ATOM + 'id') or link}", "source": src.get("label", "RSS"),
            "kind": "post", "title": _clean(e.findtext("title") or e.findtext(ATOM + "title"), 300), "url": link,
            "authors": src.get("label", ""), "published": published.date().isoformat() if published else "",
            "snippet": _clean(body),
        })
    return out


def _openalex_author_ids(people):
    """Resolve names to OpenAlex author ids once, preferring a match on the institution hint. Cached."""
    cache_file = config.path("cache", "openalex_authors.json")
    cache = json.load(open(cache_file)) if os.path.exists(cache_file) else {}
    ids = []
    for person in people:
        name, hint = (person, "") if isinstance(person, str) else (person["name"], person.get("hint", ""))
        key = f"{name}|{hint}"
        if key not in cache:
            url = "https://api.openalex.org/authors?" + urllib.parse.urlencode({"search": name, "per-page": 10})
            results = json.loads(get(url)).get("results", [])
            insts = lambda a: " ".join(i.get("display_name", "") for i in a.get("last_known_institutions") or [])
            pick = next((a for a in results if hint and hint.lower() in insts(a).lower()), results[0] if results else None)
            cache[key] = pick["id"].rsplit("/", 1)[-1] if pick else ""
        if cache[key]:
            ids.append(cache[key])
    config.write_private(cache_file, json.dumps(cache, indent=1))
    return ids


def _abstract(inv):
    if not inv:
        return ""
    words = sorted((i, w) for w, positions in inv.items() for i in positions)
    return " ".join(w for _, w in words)


def openalex(src):
    """New works by watched authors (journals included, not just arXiv)."""
    since = _since(src.get("days", 30)).date().isoformat()
    ids = _openalex_author_ids(src.get("authors", []))
    out = {}
    for k in range(0, len(ids), 25):
        url = "https://api.openalex.org/works?" + urllib.parse.urlencode({
            "filter": f"author.id:{'|'.join(ids[k:k + 25])},from_publication_date:{since}",
            "sort": "publication_date:desc", "per-page": 50})
        for w in json.loads(get(url)).get("results", []):
            wid = w["id"].rsplit("/", 1)[-1]
            names = [a["author"]["display_name"] for a in w.get("authorships", [])]
            out[wid] = {
                "id": f"openalex:{wid}", "source": "OpenAlex", "kind": "paper",
                "title": _clean(w.get("display_name") or "", 300),
                "url": w.get("doi") or (w.get("primary_location") or {}).get("landing_page_url") or w["id"],
                "authors": ", ".join(names[:8]) + (" et al." if len(names) > 8 else ""),
                "published": w.get("publication_date") or "",
                "snippet": _clean(_abstract(w.get("abstract_inverted_index"))),
            }
    return list(out.values())


def page(src):
    """A whole events page as one item. It is re-judged only when its text changes."""
    raw = get(src["url"]).decode("utf-8", "replace")
    raw = re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1>", " ", raw)
    text = _clean(raw, 100000)
    if src.get("start") and src["start"] in text:
        text = text[text.index(src["start"]):]
    text = text[: src.get("chars", 6000)]
    digest = hashlib.sha1(text.encode()).hexdigest()[:12]
    return [{
        "id": f"page:{src['url']}#{digest}", "source": src.get("label", "Events"), "kind": "events page",
        "title": f"{src.get('label', 'Events')}: upcoming events", "url": src["url"], "authors": "",
        "published": datetime.date.today().isoformat(), "snippet": text,
    }]


def _event_day(iso):
    return (iso or "")[:10]


def _within(iso, days_ahead):
    d = _date(iso)
    now = datetime.datetime.now(datetime.timezone.utc)
    return d is not None and now - datetime.timedelta(hours=6) <= d <= now + datetime.timedelta(days=days_ahead)


def _home():
    """Where you live, from config.json: {"home": {"timezone": "...", "cities": ["..."]}}."""
    try:
        return config.load().get("home") or {}
    except FileNotFoundError:
        return {}


def _local(iso, tz=None):
    d = _date(iso)
    if not d:
        return ""
    try:
        from zoneinfo import ZoneInfo
        d = d.astimezone(ZoneInfo(tz or _home().get("timezone") or "UTC"))
    except Exception:
        pass
    return d.strftime("%a %b %-d, %-I:%M%p").replace(":00", "")


def _luma_id(slug, kind):
    """'claudecommunity' -> cal-..., 'nyc' -> discplace-...; ids pass through. Cached in LUCKBOX_HOME."""
    if slug.startswith(("cal-", "discplace-", "cat-")):
        return slug
    cache_file = config.path("cache", "luma_ids.json")
    cache = json.load(open(cache_file)) if os.path.exists(cache_file) else {}
    if slug not in cache:
        if kind == "category":
            d = json.loads(get("https://api.lu.ma/discover/category/get-page?" + urllib.parse.urlencode({"slug": slug})))
            cache[slug] = (d.get("category") or {}).get("api_id", "")
        else:
            d = json.loads(get("https://api.lu.ma/url?" + urllib.parse.urlencode({"url": slug}))).get("data") or {}
            cache[slug] = ((d.get("calendar") or d.get("place")) or {}).get("api_id", "")
        config.write_private(cache_file, json.dumps(cache, indent=1))
    return cache[slug]


def luma(src):
    """Luma events: categories (localized to where you are), specific community calendars, and
    a place's popular list. Hosts and featured guests come along, so known people can be spotted."""
    days = src.get("days_ahead", 30)
    city = [c.lower() for c in src.get("cities") or _home().get("cities") or []]
    entries = []

    def pages(params, n):
        cursor = None
        for _ in range(n):
            q = dict(params, pagination_limit=50)
            if cursor:
                q["pagination_cursor"] = cursor
            r = json.loads(get(f"https://api.lu.ma/{q.pop('_path')}?" + urllib.parse.urlencode(q)))
            entries.extend(r.get("entries", []))
            if not r.get("has_more"):
                break
            cursor = r.get("next_cursor")

    for cat in src.get("categories", []):
        pages({"_path": "discover/get-paginated-events", "discover_category_api_id": _luma_id(cat, "category")},
              src.get("max_pages", 3))
    for cal in src.get("calendars", []):
        pages({"_path": "calendar/get-items", "calendar_api_id": _luma_id(cal, "calendar"), "period": "future"}, 2)
    if src.get("place"):
        pages({"_path": "discover/get-paginated-events", "discover_place_api_id": _luma_id(src["place"], "place")}, 2)

    out = {}
    for e in entries:
        ev = e.get("event") or {}
        if not ev.get("api_id") or not _within(ev.get("start_at"), days):
            continue
        geo = ev.get("geo_address_info") or {}
        where = geo.get("full_address") or geo.get("city_state") or geo.get("city") or ""
        online = ev.get("location_type") == "online" or (not where and ev.get("virtual_info"))
        if city and not online and not any(c in where.lower() for c in city):
            continue
        hosts = [f"{h.get('name')}" + (f" ({h['bio_short'][:80]})" if h.get("bio_short") else "") for h in e.get("hosts") or []]
        guests = [g.get("name") for g in e.get("featured_guests") or [] if g.get("name")]
        cal = (e.get("calendar") or {}).get("name", "")
        out[ev["api_id"]] = {
            "id": f"luma:{ev['api_id']}", "source": "Luma", "kind": "event", "title": ev.get("name", ""),
            "url": f"https://luma.com/{ev.get('url', '')}", "authors": ", ".join(h.split(" (")[0] for h in hosts)[:300],
            "published": _event_day(ev.get("start_at")),
            "snippet": _clean(f"{_local(ev.get('start_at'))} · {'online' if online else where} · calendar: {cal} · hosts: "
                              f"{'; '.join(hosts)} · {e.get('guest_count') or 0} going"
                              + (f" · featured guests: {', '.join(guests[:15])}" if guests else ""), 1200),
        }
    return list(out.values())


def partiful(src):
    """Partiful's public trending list for a city. Most Partiful events are private invites, so this is thin."""
    raw = get("https://partiful.com/explore").decode("utf-8", "replace")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', raw, re.S)
    if not m:
        return []
    section = json.loads(m.group(1))["props"]["pageProps"].get("trendingSections", {}).get(src.get("city", "NYC"), {})
    out = []
    for it in section.get("items", []):
        ev = it.get("event") or {}
        if not ev.get("id") or not _within(ev.get("startDate"), src.get("days_ahead", 30)):
            continue
        loc = ev.get("locationInfo") or {}
        where = loc.get("displayName") if isinstance(loc, dict) else ""
        out.append({
            "id": f"partiful:{ev['id']}", "source": "Partiful", "kind": "event", "title": ev.get("title", ""),
            "url": f"https://partiful.com/e/{ev['id']}", "authors": "", "published": _event_day(ev.get("startDate")),
            "snippet": _clean(f"{_local(ev.get('startDate'))} · {where or 'NYC'} · {ev.get('goingGuestCount') or 0} going · "
                              f"{ev.get('description') or ''}"),
        })
    return out


def seminars(src):
    """Upcoming talks from researchseminars.org, by topic (e.g. cond-mat_stat-mech). Mostly online, worldwide."""
    now = datetime.datetime.now(datetime.timezone.utc)
    end = now + datetime.timedelta(days=src.get("days_ahead", 30))
    out = {}
    for topic in src["topics"]:
        url = "https://researchseminars.org/api/0/search/talks?" + urllib.parse.urlencode({
            "topics": json.dumps({"$contains": [topic]}),
            "start_time": json.dumps({"$gte": now.isoformat(), "$lte": end.isoformat()})})
        for t in json.loads(get(url)).get("results", []):
            key = f"{t.get('seminar_id')}/{t.get('seminar_ctr')}"
            if not t.get("title") or key in out:
                continue
            speaker = ", ".join(x for x in [t.get("speaker"), t.get("speaker_affiliation")] if x)
            where = "online" if t.get("online") else (t.get("room") or t.get("institutions") or "in person")
            out[key] = {
                "id": f"seminar:{key}", "source": "researchseminars.org", "kind": "event", "title": _clean(t["title"], 300),
                "url": f"https://researchseminars.org/talk/{key}/", "authors": speaker[:300],
                "published": _event_day(t.get("start_time")),
                "snippet": _clean(f"{_local(t.get('start_time'))} · {where} · series {t.get('seminar_id')} · "
                                  f"{t.get('abstract') or ''}"),
            }
    return list(out.values())


def followups(src):
    """Moves you marked done N+ days ago with no reply marked: a nudge to follow up, once."""
    from .. import ledger
    con = ledger.connect()
    after = src.get("after_days", 10)
    rows = con.execute(
        "SELECT s.id, s.day, s.move, s.url, j.person FROM suggestion s JOIN judgment j ON j.item_id = s.item_id"
        " WHERE s.mark = 'done' AND COALESCE(j.person, '') != '' AND s.marked_at < datetime('now', ?)"
        " AND s.marked_at > datetime('now', ?)",
        (f"-{after} days", f"-{after + 21} days")).fetchall()
    return [{
        "id": f"followup:{r['id']}", "source": "Follow-up", "kind": "followup",
        "title": f"Follow up with {r['person']}", "url": r["url"] or "", "authors": r["person"],
        "published": datetime.date.today().isoformat(),
        "snippet": f"On {r['day']} you did: {r['move']} No reply marked since.",
    } for r in rows]


READERS = {"hn": hn, "arxiv": arxiv, "rss": rss, "openalex": openalex, "page": page,
           "luma": luma, "partiful": partiful, "seminars": seminars, "followups": followups}
