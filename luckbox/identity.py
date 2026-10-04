"""Matching one person across sources, and the two lists that decide who gets indexed at all."""
import csv
import os
import re
import unicodedata

from . import config


def name_key(name):
    """'Tapia, Caridad' and 'Caridad M. Tapia' both become 'caridad tapia'."""
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\(.*?\)", " ", n)
    if "," in n:
        last, _, first = n.partition(",")
        n = f"{first} {last}"
    tokens = re.sub(r"[^a-z ]", " ", n).split()
    return f"{tokens[0]} {tokens[-1]}" if len(tokens) >= 2 else ""


def _phone(s):
    digits = re.sub(r"\D", "", s)
    return digits[-10:] if len(digits) >= 7 else ""


class Exclusions:
    """exclude.txt: one name, email, phone or handle per line. Matches are dropped before anything else."""

    def __init__(self, lines):
        self.emails, self.names, self.phones, self.handles = set(), set(), set(), set()
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if "@" in line and "." in line.split("@")[-1]:
                self.emails.add(line.lower())
            elif _phone(line) and not re.search(r"[a-zA-Z]", line):
                self.phones.add(_phone(line))
            elif name_key(line):
                self.names.add(name_key(line))
            else:
                self.handles.add(line.lower().lstrip("@"))

    @classmethod
    def load(cls):
        p = config.path("exclude.txt")
        return cls(open(p).read().splitlines()) if os.path.exists(p) else cls([])

    def __len__(self):
        return len(self.emails) + len(self.names) + len(self.phones) + len(self.handles)

    def match(self, name="", emails=(), phones=(), handles=()):
        if name_key(name) and name_key(name) in self.names:
            return True
        if any(e.lower() in self.emails for e in emails):
            return True
        if any(_phone(p) in self.phones for p in phones if _phone(p)):
            return True
        return any(h.lower().lstrip("@") in self.handles for h in handles)


DECISIONS = ("inner", "keep", "nosuggest", "drop")


class Decisions:
    """decisions.tsv: email, decision, label, note. Keyed by email; a bare name also works."""

    def __init__(self, rows):
        self.by_email, self.by_name = {}, {}
        for r in rows:
            who = r["email"].strip()
            if r["decision"] not in DECISIONS:
                continue
            if "@" in who:
                self.by_email[who.lower()] = r
            elif name_key(who):
                self.by_name[name_key(who)] = r

    @classmethod
    def load(cls):
        p = config.path("people", "decisions.tsv")
        if not os.path.exists(p):
            return cls([])
        lines = [l for l in open(p) if l.strip() and not l.startswith("#")]
        fields = ["email", "decision", "label", "note"]
        return cls(dict(zip(fields, (c or "" for c in row + [""] * 4))) for row in csv.reader(lines, delimiter="\t"))

    def lookup(self, name, emails):
        for e in emails:
            if e.lower() in self.by_email:
                return self.by_email[e.lower()]
        return self.by_name.get(name_key(name))


def record(who, decision, label="", note=""):
    """Add or replace one line in decisions.tsv."""
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {', '.join(DECISIONS)}")
    p = config.path("people", "decisions.tsv")
    lines = open(p).read().splitlines() if os.path.exists(p) else ["# email\tdecision\tlabel\tnote"]
    key = who.strip().lower()
    lines = [l for l in lines if l.startswith("#") or l.split("\t", 1)[0].strip().lower() != key]
    lines.append("\t".join([who.strip(), decision, label, note]))
    config.write_private(p, "\n".join(lines) + "\n")
