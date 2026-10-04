import os
import sqlite3
import tempfile
import unittest

from luckbox import ledger, people, store


class People(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LUCKBOX_HOME"] = self.tmp.name
        con, tmp = store.fresh()
        con.execute("INSERT INTO person (id, key, name, decision, label) VALUES (1, 'ada lovelace', 'Ada Lovelace', 'keep', 'mentor')")
        con.execute("INSERT INTO handle VALUES (1, 'email', 'ada@engine.org')")
        con.execute("INSERT INTO interaction VALUES (1, 'mail', 3, 4, 0, '2024-01-01', '2025-02-01', '[]', '')")
        con.execute("INSERT INTO person (id, key, name, decision, label) VALUES (2, 'bob smith', 'Bob Smith', 'keep', 'friend')")
        con.execute("INSERT INTO handle VALUES (2, 'email', 'bob@gmail.com')")
        store.commit(con, tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def test_done_mark_updates_last_contact(self):
        con = ledger.connect()
        con.execute("INSERT INTO item (id, radar, title) VALUES ('x', 'r', 't')")
        con.execute("INSERT INTO judgment (item_id, pass, score, person) VALUES ('x', 1, 0.9, 'Ada B. Lovelace')")
        con.execute("INSERT INTO suggestion (item_id, day, rank, mark) VALUES ('x', '2026-10-03', 1, 'done')")
        con.commit()
        ada = next(p for p in people.core() if p["name"] == "Ada Lovelace")
        self.assertEqual(ada["last"], "2026-10-03")

    def test_anchor_skips_personal_addresses(self):
        found = {p["name"]: people.anchor(p) for p in people.core()}
        self.assertEqual(found["Ada Lovelace"], "engine.org")
        self.assertEqual(found["Bob Smith"], "")


if __name__ == "__main__":
    unittest.main()


class Grow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LUCKBOX_HOME"] = self.tmp.name
        os.makedirs(os.path.join(self.tmp.name, "people"))
        con, tmp = store.fresh()
        con.execute("INSERT INTO person (id, key, name, decision) VALUES (1, 'ada lovelace', 'Ada Lovelace', 'keep')")
        store.commit(con, tmp)
        con = ledger.connect()
        for iid, person in (("a", "Grace Hopper, cc Alan Turing"), ("b", "Ada B. Lovelace")):
            con.execute("INSERT INTO item (id, radar, source, title) VALUES (?, 'r', 'arXiv', 'A paper')", (iid,))
            con.execute("INSERT INTO judgment (item_id, pass, score, person) VALUES (?, 1, 0.9, ?)", (iid, person))
        con.execute("INSERT INTO suggestion (item_id, day, rank) VALUES ('a', '2026-10-03', 1)")
        con.execute("INSERT INTO suggestion (item_id, day, rank) VALUES ('b', '2026-10-03', 2)")
        con.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def test_done_adds_new_person_once_with_anchor(self):
        from luckbox import identity, marks
        marks.apply("2026-10-03", 1, "done")
        marks.apply("2026-10-03", 1, "replied")
        marks.apply("2026-10-03", 2, "done")  # already known: not added again
        d = identity.Decisions.load()
        grace = d.lookup("Grace Hopper", [])
        self.assertEqual((grace["decision"], grace["label"]), ("keep", "via luckbox"))
        self.assertIn("anchor: arXiv: A paper", grace["note"])
        self.assertIsNone(d.lookup("Alan Turing", []))
        self.assertIsNone(d.lookup("Ada Lovelace", []))

    def test_good_does_not_add(self):
        from luckbox import identity, marks
        marks.apply("2026-10-03", 1, "good")
        self.assertIsNone(identity.Decisions.load().lookup("Grace Hopper", []))
