"""The people you know, as context for the judge: who they are, how you know them, and when you
last spoke (from mail archives, plus every move you mark done or replied)."""
import re

from . import ledger, store

PERSONAL = ("gmail.com", "yahoo.com", "hotmail.com", "icloud.com", "outlook.com", "me.com", "proton.me")


def core(decisions=("inner", "keep")):
    con = store.connect()
    q = ",".join("?" * len(decisions))
    people = []
    for p in con.execute(f"SELECT * FROM person WHERE decision IN ({q}) ORDER BY decision, label, name", decisions):
        emails = [r["value"] for r in con.execute("SELECT value FROM handle WHERE person_id = ?", (p["id"],))]
        li = con.execute("SELECT position, company FROM linkedin WHERE person_id = ?", (p["id"],)).fetchone()
        last = con.execute("SELECT MAX(last) FROM interaction WHERE person_id = ?", (p["id"],)).fetchone()[0] or ""
        domains = sorted({e.split("@")[-1] for e in emails if e.split("@")[-1] not in PERSONAL})
        people.append({"name": p["name"], "decision": p["decision"], "label": p["label"] or "", "note": p["note"] or "",
                       "role": f"{li['position']} @ {li['company']}" if li else "", "domains": domains, "last": last})
    marked = last_marked()
    for p in people:
        p["last"] = max(p["last"], marked.get(_key(p["name"]), ""))
    return people


def _key(name):
    from .identity import name_key
    k = name_key(name)
    return f"{k[0]} {k.split()[-1]}" if k else ""


def last_marked():
    """Contact you made through luckbox: moves marked done or replied, by the person they name."""
    con = ledger.connect()
    out = {}
    for r in con.execute("SELECT j.person, s.day FROM suggestion s JOIN judgment j ON j.item_id = s.item_id"
                         " WHERE s.mark IN ('done', 'replied') AND COALESCE(j.person, '') != ''"):
        for name in re.split(r",| and |&", r["person"]):
            k = _key(name.strip())
            if k:
                out[k] = max(out.get(k, ""), r["day"])
    return out


def anchor(p):
    """What makes a web search find this person and not a namesake. Empty means: don't search."""
    m = re.search(r"anchor:\s*([^;]+)", p.get("note") or "")
    if m:
        return m.group(1).strip()
    if p["role"]:
        return p["role"]
    return ", ".join(p["domains"])


def summary():
    lines = ["People you know. Labels say how; notes say what happened; last = last contact you had."]
    for p in core():
        bits = [p["label"], p["role"] or ", ".join(p["domains"]), p["note"], f"last {p['last']}" if p["last"] else ""]
        lines.append(f"- {p['name']}: " + "; ".join(b for b in bits if b))
    return "\n".join(lines)
