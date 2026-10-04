"""A prepared contacts CSV, e.g. one an agent wrote from a live inbox.

Columns: name, email (several separated by ';'), company, internal, you_sent, they_sent,
meetings, first, last, context, and optionally subjects (separated by ' | ')."""
import csv


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def read(src, me=()):
    out = []
    with open(src["path"], newline="") as f:
        for r in csv.DictReader(f):
            out.append({
                "name": r.get("name", "").strip(),
                "emails": [e.strip().lower() for e in r.get("email", "").split(";") if e.strip()],
                "you_sent": _int(r.get("you_sent")),
                "they_sent": _int(r.get("they_sent")),
                "meetings": _int(r.get("meetings")),
                "first": r.get("first", ""),
                "last": r.get("last", ""),
                "subjects": [x for x in (r.get("subjects") or "").split(" | ") if x],
                "context": r.get("context", ""),
            })
    return out
