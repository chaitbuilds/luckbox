"""LinkedIn data export. Connections become a lookup table, not people: a connection alone says
nothing about a relationship, but it answers "do I know anyone at X?"."""
import csv
import io
import zipfile


def _rows(z, name, header_prefix=None):
    text = z.read(name).decode("utf-8", "replace")
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith(header_prefix)), 0) if header_prefix else 0
    return list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))


def read(src):
    z = zipfile.ZipFile(src["path"])
    names = set(z.namelist())
    notes = {}
    if "Invitations.csv" in names:
        for r in _rows(z, "Invitations.csv"):
            if r.get("Message", "").strip():
                who = r["From"] if r.get("Direction") == "INCOMING" else r["To"]
                notes[who.strip().lower()] = r.get("Direction", "").lower()
    out = []
    for r in _rows(z, "Connections.csv", "First Name"):
        name = f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip()
        out.append({
            "name": name,
            "email": (r.get("Email Address") or "").strip().lower(),
            "company": (r.get("Company") or "").strip(),
            "position": (r.get("Position") or "").strip(),
            "connected_on": r.get("Connected On", ""),
            "url": r.get("URL", ""),
            "invite_note": notes.get(name.lower(), ""),
        })
    return out
