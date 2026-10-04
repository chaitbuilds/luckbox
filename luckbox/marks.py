"""Marking a move. 'done' and 'replied' also grow your network: the person the move named becomes
someone you know, so their updates get watched and later moves can build on the contact."""
import datetime
import re

from . import identity, ledger, people

MARKS = ("good", "weak", "done", "replied")


OPEN = (None, "good")  # unmarked, or kept for later: still on your list


def apply(day, n, mark, note=""):
    """Mark today's (or a given day's) move number n."""
    row = ledger.connect().execute("SELECT id FROM suggestion WHERE day = ? AND rank = ?", (day, int(n))).fetchone()
    return apply_id(row["id"], mark, note) if row else False


def apply_id(sid, mark, note=""):
    """good keeps a move on your list; done, replied and weak (dismiss) take it off. done and replied
    also add the person it named to the people you know."""
    if mark not in MARKS:
        raise ValueError(f"mark must be one of {', '.join(MARKS)}")
    con = ledger.connect()
    cur = con.execute("UPDATE suggestion SET mark = ?, note = ?, marked_at = ? WHERE id = ?",
                      (mark, note or "", datetime.datetime.now().isoformat(timespec="seconds"), int(sid)))
    con.commit()
    if not cur.rowcount:
        return False
    if mark in ("done", "replied"):
        row = con.execute("SELECT s.day, j.person, i.title, i.source FROM suggestion s JOIN judgment j ON j.item_id = s.item_id"
                          " JOIN item i ON i.id = s.item_id WHERE s.id = ?", (int(sid),)).fetchone()
        if row and row["person"]:
            remember(row["person"], f"{row['source']}: {row['title'][:90]}", row["day"])
    return True


def remember(person, context, day):
    """Add the first person a move named, unless they're already known or decided."""
    name = re.split(r",| and |&|\bcc\b|\(", person)[0].strip()
    if not identity.name_key(name):
        return
    known = {people._key(p["name"]) for p in people.core(("inner", "keep", "nosuggest", "drop"))}
    if people._key(name) in known or identity.Decisions.load().lookup(name, []):
        return
    identity.record(name, "keep", "via luckbox", f"anchor: {context}; first contact {day}")
