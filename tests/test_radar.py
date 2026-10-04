import datetime
import os
import tempfile
import unittest
from unittest import mock

from luckbox import brief, judge, ledger
from luckbox.radar import sources

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Fresh &amp; relevant</title><link>https://ex.com/a</link><guid>a</guid>
<pubDate>{now}</pubDate><description>&lt;p&gt;Body text&lt;/p&gt;</description></item>
<item><title>Old</title><link>https://ex.com/b</link><guid>b</guid><pubDate>Mon, 01 Jan 2001 00:00:00 +0000</pubDate></item>
</channel></rss>"""


class Sources(unittest.TestCase):
    def test_rss_keeps_recent_and_strips_html(self):
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
        with mock.patch.object(sources, "get", return_value=RSS.replace(b"{now}", now.encode())):
            items = sources.rss({"url": "https://ex.com/feed", "label": "Ex"})
        self.assertEqual([i["title"] for i in items], ["Fresh & relevant"])
        self.assertEqual(items[0]["snippet"], "Body text")
        self.assertEqual(items[0]["id"], "rss:a")


class Parse(unittest.TestCase):
    def test_accepts_fenced_json(self):
        got = judge.parse('```json\n[{"id": "x", "pass": true}]\n```', ["x"])
        self.assertTrue(got["x"]["pass"])

    def test_rejects_missing_ids(self):
        with self.assertRaises(ValueError):
            judge.parse('[{"id": "x"}]', ["x", "y"])

    def test_rejects_prose(self):
        with self.assertRaises(ValueError):
            judge.parse("I could not complete this.", ["x"])


class Brief(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LUCKBOX_HOME"] = self.tmp.name
        self.con = ledger.connect()
        today = datetime.date.today().isoformat()
        for i, (score, ok, src) in enumerate([(0.9, 1, "A"), (0.8, 1, "A"), (0.7, 1, "A"), (0.65, 1, "B"),
                                              (0.5, 1, "B"), (0.95, 0, "B")]):
            self.con.execute("INSERT INTO item (id, radar, source, title, url, published) VALUES (?,?,?,?,?,?)",
                             (f"i{i}", "r", src, f"t{i}", f"u{i}", today))
            self.con.execute("INSERT INTO judgment (item_id, pass, score, move, why) VALUES (?,?,?,?,?)",
                             (f"i{i}", ok, score, f"move {i}", "why"))
        self.con.commit()
        self.radars = [{"name": "r", "min_score": 0.6, "max_per_day": 5, "max_per_source": 2}]

    def tearDown(self):
        self.tmp.cleanup()

    def test_threshold_source_cap_and_failures(self):
        rows = brief.make(self.con, self.radars, datetime.date.today())
        self.assertEqual([r["item_id"] for r in rows], ["i0", "i1", "i3"])

    def test_picks_once_per_day(self):
        first = [r["item_id"] for r in brief.make(self.con, self.radars, datetime.date.today())]
        again = [r["item_id"] for r in brief.make(self.con, self.radars, datetime.date.today())]
        self.assertEqual(first, again)

    def test_never_resuggests(self):
        brief.make(self.con, self.radars, datetime.date.today())
        tomorrow = brief.make(self.con, self.radars, datetime.date.today() + datetime.timedelta(days=1))
        # i2 was held back by the per-source cap yesterday, so it is today's only pick.
        self.assertEqual([r["item_id"] for r in tomorrow], ["i2"])


if __name__ == "__main__":
    unittest.main()


class MoreSources(unittest.TestCase):
    def test_openalex_abstract_rebuilds_word_order(self):
        self.assertEqual(sources._abstract({"memory": [1], "Training": [0], "matters": [2]}), "Training memory matters")

    def test_page_ignores_scripts_and_changes_id_with_text(self):
        a = b"<html><script>var x=1</script><nav>menu</nav><main>Talk: Oct 9, Speaker A</main></html>"
        b = a.replace(b"Oct 9", b"Oct 10")
        with mock.patch.object(sources, "get", return_value=a):
            first = sources.page({"url": "https://ex.com/events", "label": "Ex"})[0]
        with mock.patch.object(sources, "get", return_value=b):
            second = sources.page({"url": "https://ex.com/events", "label": "Ex"})[0]
        self.assertEqual(first["snippet"], "Talk: Oct 9, Speaker A")
        self.assertNotEqual(first["id"], second["id"])


class Events(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LUCKBOX_HOME"] = self.tmp.name
        self.con = ledger.connect()
        today = datetime.date.today()
        rows = [("past", "event", today - datetime.timedelta(days=1)), ("soon", "event", today + datetime.timedelta(days=5)),
                ("paper", "paper", today - datetime.timedelta(days=3))]
        for iid, kind, day in rows:
            self.con.execute("INSERT INTO item (id, radar, source, kind, title, url, published) VALUES (?,?,?,?,?,?,?)",
                             (iid, "r", iid, kind, iid, iid, day.isoformat()))
            self.con.execute("INSERT INTO judgment (item_id, pass, score, move, why) VALUES (?,?,?,?,?)",
                             (iid, 1, 0.9, "m", "w"))
        self.con.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def test_past_events_never_suggested(self):
        rows = brief.make(self.con, [{"name": "r", "max_per_source": 5}], datetime.date.today())
        self.assertEqual(sorted(r["item_id"] for r in rows), ["paper", "soon"])

    def test_luma_keeps_nyc_and_online_only(self):
        soon = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)).isoformat()
        payload = {"entries": [
            {"event": {"api_id": "a", "name": "NYC", "start_at": soon, "url": "a", "geo_address_info": {"city": "New York"}}},
            {"event": {"api_id": "b", "name": "SF", "start_at": soon, "url": "b", "geo_address_info": {"city": "San Francisco"}}},
            {"event": {"api_id": "c", "name": "Online", "start_at": soon, "url": "c", "location_type": "online"}}],
            "has_more": False}
        import json as _json
        with mock.patch.object(sources, "get", return_value=_json.dumps(payload).encode()):
            got = sources.luma({"categories": ["cat-x"], "cities": ["new york"]})
        self.assertEqual(sorted(i["title"] for i in got), ["NYC", "Online"])


class Known(unittest.TestCase):
    def test_initials_and_nicknames_match(self):
        names = {brief._initial_key("Ada Lovelace"), brief._initial_key("Charles Babbage")}
        self.assertTrue(brief.involves_known({"authors": "Grace Wang, Ada B. Lovelace", "snippet": ""}, names))
        self.assertTrue(brief.involves_known({"authors": "", "snippet": "hosts: Charlie Babbage (RI)"}, names))
        self.assertFalse(brief.involves_known({"authors": "Ada Lowell", "snippet": "a talk on babbage engines"}, names))


class Marks(unittest.TestCase):
    def test_recent_marks_reach_the_prompt(self):
        with tempfile.TemporaryDirectory() as home:
            os.environ["LUCKBOX_HOME"] = home
            con = ledger.connect()
            con.execute("INSERT INTO item (id, radar, title) VALUES ('a', 'r', 't')")
            con.execute("INSERT INTO suggestion (item_id, day, rank, move, mark, note, marked_at)"
                        " VALUES ('a', '2026-10-03', 1, 'Email X', 'weak', 'too generic', '2026-10-03T09:00')")
            con.commit()
            m = judge.recent_marks(con, "r")
            self.assertIn("weak: Email X (note: too generic)", m)
            self.assertIn("<YOUR_MARKS>", judge.prompt_for("ctx", [], "", m))
            self.assertNotIn("<YOUR_MARKS>", judge.prompt_for("ctx", [], "", ""))


class OpenList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LUCKBOX_HOME"] = self.tmp.name
        self.con = ledger.connect()
        self.today = datetime.date(2026, 10, 20)
        d = lambda n: (self.today - datetime.timedelta(days=n)).isoformat()
        rows = [  # id, kind, published, suggested day, mark
            ("fresh", "paper", d(1), d(1), None), ("stale", "paper", d(20), d(12), None),
            ("kept", "paper", d(30), d(20), "good"), ("done", "paper", d(1), d(1), "done"),
            ("dismissed", "post", d(1), d(1), "weak"), ("past_event", "event", d(1), d(3), None),
            ("next_event", "event", d(-5), d(3), None)]
        for n, (iid, kind, pub, day, mark) in enumerate(rows):
            self.con.execute("INSERT INTO item (id, radar, kind, title, url, published) VALUES (?,?,?,?,?,?)",
                             (iid, "r", kind, iid, iid, pub))
            self.con.execute("INSERT INTO suggestion (item_id, day, rank, move, mark) VALUES (?,?,?,?,?)",
                             (iid, day, n, iid, mark))
        self.con.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_keeps_open_and_kept_moves_until_cleared_or_expired(self):
        got = sorted(r["item_id"] for r in brief.open_moves(self.con, self.today))
        self.assertEqual(got, ["fresh", "kept", "next_event"])


class Followups(unittest.TestCase):
    def test_done_without_reply_comes_back_once_due(self):
        with tempfile.TemporaryDirectory() as home:
            os.environ["LUCKBOX_HOME"] = home
            con = ledger.connect()
            for sid, (days_ago, mark) in enumerate([(12, "done"), (3, "done"), (12, "replied"), (40, "done")], 1):
                con.execute("INSERT INTO item (id, radar, title) VALUES (?, 'r', 't')", (f"i{sid}",))
                con.execute("INSERT INTO judgment (item_id, pass, score, person) VALUES (?, 1, 0.9, 'Ada Lovelace')", (f"i{sid}",))
                con.execute("INSERT INTO suggestion (id, item_id, day, rank, move, mark, marked_at)"
                            " VALUES (?, ?, '2026-09-01', ?, 'Email Ada', ?, datetime('now', ?))",
                            (sid, f"i{sid}", sid, mark, f"-{days_ago} days"))
            con.commit()
            got = sources.followups({"after_days": 10})
            self.assertEqual([g["id"] for g in got], ["followup:1"])


class Weekly(unittest.TestCase):
    def test_every_days_radar_picks_at_most_weekly(self):
        with tempfile.TemporaryDirectory() as home:
            os.environ["LUCKBOX_HOME"] = home
            con = ledger.connect()
            today = datetime.date.today()
            for iid in ("a", "b"):
                con.execute("INSERT INTO item (id, radar, kind, title, url, published) VALUES (?, 'w', 'post', ?, ?, ?)",
                            (iid, iid, iid, today.isoformat()))
                con.execute("INSERT INTO judgment (item_id, pass, score, move) VALUES (?, 1, 0.9, 'm')", (iid,))
            con.commit()
            radar = [{"name": "w", "every_days": 7, "max_per_day": 1}]
            self.assertEqual(len(brief.make(con, radar, today, limit=5)), 1)
            self.assertEqual(len(brief.make(con, radar, today + datetime.timedelta(days=3), limit=5)), 0)
            self.assertEqual(len(brief.make(con, radar, today + datetime.timedelta(days=8), limit=5)), 1)


class Backfill(unittest.TestCase):
    def test_first_fetch_widens_windows_only_for_feeds(self):
        from luckbox.cli import first_fetch_window
        self.assertEqual(first_fetch_window({"type": "arxiv", "days": 7})["days"], 28)
        self.assertEqual(first_fetch_window({"type": "hn"})["days"], 12)
        self.assertNotIn("days", first_fetch_window({"type": "luma"}))
