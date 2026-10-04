import os
import tempfile
import unittest

from luckbox import identity


class NameKey(unittest.TestCase):
    def test_comma_and_middle_names(self):
        self.assertEqual(identity.name_key("Tapia, Caridad"), "caridad tapia")
        self.assertEqual(identity.name_key("Caridad M. Tapia"), "caridad tapia")
        self.assertEqual(identity.name_key("Katherine(Yidi) Pei"), "katherine pei")

    def test_single_token_has_no_key(self):
        self.assertEqual(identity.name_key("Stephen"), "")


class Exclude(unittest.TestCase):
    def setUp(self):
        self.x = identity.Exclusions(["# comment", "Jane Doe", "ex@example.com", "+1 (555) 010-2030", "@handle"])

    def test_matches_each_kind(self):
        self.assertTrue(self.x.match("Jane A. Doe"))
        self.assertTrue(self.x.match("", ["EX@example.com"]))
        self.assertTrue(self.x.match("", phones=["555-010-2030"]))
        self.assertTrue(self.x.match("", handles=["Handle"]))

    def test_leaves_others(self):
        self.assertFalse(self.x.match("John Doe", ["john@example.com"]))


class Decisions(unittest.TestCase):
    def test_record_replaces_and_lookup_finds(self):
        with tempfile.TemporaryDirectory() as home:
            os.environ["LUCKBOX_HOME"] = home
            os.makedirs(os.path.join(home, "people"))
            identity.record("a@x.com", "keep", "mentor")
            identity.record("a@x.com", "drop")
            d = identity.Decisions.load()
            self.assertEqual(d.lookup("", ["A@x.com"])["decision"], "drop")
            with self.assertRaises(ValueError):
                identity.record("a@x.com", "maybe")
            self.assertEqual(oct(os.stat(os.path.join(home, "people", "decisions.tsv")).st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
