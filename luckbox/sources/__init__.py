"""Each source turns one export into contacts: dicts with name, emails, you_sent, they_sent,
meetings, first, last, subjects, context. Facts only; nothing here asks a model anything."""
from . import contacts_csv, linkedin, mbox

READERS = {"mbox": mbox.read, "contacts_csv": contacts_csv.read}
