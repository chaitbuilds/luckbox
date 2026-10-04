"""Gmail/Takeout mbox, headers only. Message bodies are never read.

Keeps a person only if both sides wrote: they sent something that isn't automated, and you sent
something that isn't a template. That one rule removes most of an inbox."""
import collections
import io
import re
import zipfile
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

# Local parts that belong to a function, not a person.
ROLE = re.compile(
    r"^(no-?reply|do-?not-?reply|notifications?|mailer|bounce|info|help|support|admin|office|registrar"
    r"|advis(ing|or)s?|contact|hello|hi|team|jobs|careers|recruit(ing|ment)?|hr|billing|accounts?|service"
    r"|services|sales|press|media|events?|admissions|financial-?aid|ask|questions|feedback|news|newsletter"
    r"|updates?|alerts?|reply|calendar|community|founders|partners|members|membership|students?|club"
    r"|orders?|receipts?|security|verify|welcome|digest|marketing|invites?|staff|dean|chair|program|programs"
    r"|center|lab|group|list|listserv|announce|confirm|undergrads?)[\d._-]*$",
    re.I,
)
# Domains where any address is a platform, not a person.
PLATFORM = re.compile(
    r"(instructure|canvas|handshake|piazza|gradescope|linkedin|google|github|calendly|zoom|slack|notion"
    r"|docusign|greenhouse|lever|workday|ashby|icims|smartrecruiters|mailchimp|hubspot|sendgrid|substack"
    r"|beehiiv|luma|eventbrite|typeform|qualtrics|youtube|facebook|instagram|apple|amazon|venmo|paypal"
    r"|stripe|emailrelay)\.",
    re.I,
)
TEMPLATE_MIN = 4  # a sent subject used this many times is a template, not a conversation


def _dec(s):
    try:
        return str(make_header(decode_header(s or "")))
    except Exception:
        return s or ""


def _subject(s):
    return re.sub(r"^((re|fwd?|fw)\s*:\s*)+", "", _dec(s), flags=re.I).strip()[:80]


def is_role_address(addr):
    local, _, domain = addr.partition("@")
    return bool(ROLE.match(local)) or bool(PLATFORM.search(domain)) or "noreply" in addr or "no-reply" in addr


def iter_headers(stream):
    """Yield one dict of lowercased headers per message from a binary mbox stream."""
    hdr, in_hdr = [], False

    def parse(lines):
        h, cur = {}, None
        for line in lines:
            if line[:1] in (" ", "\t") and cur:
                h[cur] += " " + line.strip()
            else:
                k, _, v = line.partition(":")
                cur = k.strip().lower()
                h.setdefault(cur, v.strip())
        return h

    for raw in stream:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line.startswith("From ") and not in_hdr:
            if hdr:
                yield parse(hdr)
            hdr, in_hdr = [], True
            continue
        if in_hdr:
            if line == "":
                in_hdr = False
            else:
                hdr.append(line)
    if hdr:
        yield parse(hdr)


def _open(path, member=None):
    if path.endswith(".zip"):
        z = zipfile.ZipFile(path)
        name = member or next(n for n in z.namelist() if n.endswith(".mbox"))
        return io.BufferedReader(z.open(name), buffer_size=1 << 20)
    return open(path, "rb")


def contacts(headers, me=()):
    """Reduce message headers to two-way human contacts."""
    msgs = []
    for h in headers:
        labels = h.get("x-gmail-labels", "")
        if "Spam" in labels or "Trash" in labels:
            continue
        try:
            day = parsedate_to_datetime(h.get("date", "")).date().isoformat()
        except Exception:
            day = ""
        msgs.append((h, labels, "Sent" in labels, _subject(h.get("subject", "")), day))

    me = {a.lower() for a in me}
    for h, _, sent, _, _ in msgs:
        if sent:
            me.update(a.lower() for _, a in getaddresses([h.get("from", "")]) if a)
    templates = {s for s, n in collections.Counter(s for _, _, sent, s, _ in msgs if sent).items()
                 if s and n >= TEMPLATE_MIN}

    people = collections.defaultdict(lambda: {"names": collections.Counter(), "you_sent": 0, "they_sent": 0,
                                              "first": "", "last": "", "subjects": collections.Counter()})

    def touch(addr, name, day, subject):
        p = people[addr]
        if name:
            p["names"][_dec(name).strip("\"' ")] += 1
        if day:
            p["first"] = min(p["first"] or day, day)
            p["last"] = max(p["last"], day)
        if subject:
            p["subjects"][subject] += 1
        return p

    for h, labels, sent, subject, day in msgs:
        if sent:
            if subject in templates:
                continue
            for name, addr in getaddresses([h.get("to", ""), h.get("cc", "")]):
                addr = addr.lower()
                if addr and addr not in me:
                    touch(addr, name, day, subject)["you_sent"] += 1
        else:
            if "list-unsubscribe" in h or "Category Promotions" in labels or "Category Forums" in labels:
                continue
            found = getaddresses([h.get("from", "")])
            if found and found[0][1] and found[0][1].lower() not in me:
                touch(found[0][1].lower(), found[0][0], day, subject)["they_sent"] += 1

    out = []
    for addr, p in people.items():
        if p["you_sent"] == 0 or p["they_sent"] == 0 or is_role_address(addr):
            continue
        out.append({
            "name": p["names"].most_common(1)[0][0] if p["names"] else "",
            "emails": [addr],
            "you_sent": p["you_sent"],
            "they_sent": p["they_sent"],
            "meetings": 0,
            "first": p["first"],
            "last": p["last"],
            "subjects": [s for s, _ in p["subjects"].most_common(5)],
            "context": "",
        })
    return out


def read(src, me=()):
    with _open(src["path"], src.get("member")) as stream:
        return contacts(iter_headers(stream), me)
