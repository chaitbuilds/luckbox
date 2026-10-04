import io
import unittest

from luckbox.sources import mbox

ME = "ada@example.edu"


def msg(frm, to, subject, labels, extra=""):
    return (f"From 1@xxx Mon Jan 01 00:00:00 +0000 2025\n"
            f"X-Gmail-Labels: {labels}\nFrom: {frm}\nTo: {to}\nSubject: {subject}\n"
            f"Date: Mon, 1 Jan 2025 10:00:00 +0000\n{extra}\nbody that is never read\n\n")


def run(*messages):
    data = "".join(messages).encode()
    return {c["emails"][0]: c for c in mbox.contacts(mbox.iter_headers(io.BytesIO(data)))}


class TwoWay(unittest.TestCase):
    def test_human_who_wrote_back_is_kept(self):
        found = run(msg(f"Ada <{ME}>", "Grace Hopper <grace@navy.mil>", "Compilers", "Sent"),
                    msg("Grace Hopper <grace@navy.mil>", ME, "Re: Compilers", "Inbox,Category Personal"))
        self.assertEqual(found["grace@navy.mil"]["name"], "Grace Hopper")
        self.assertEqual((found["grace@navy.mil"]["you_sent"], found["grace@navy.mil"]["they_sent"]), (1, 1))

    def test_one_way_is_dropped(self):
        self.assertEqual(run(msg(f"Ada <{ME}>", "x@corp.com", "Hello?", "Sent")), {})

    def test_template_send_does_not_count(self):
        blast = [msg(f"Ada <{ME}>", f"p{i}@co{i}.com", "Quick question", "Sent") for i in range(4)]
        reply = msg("P0 <p0@co0.com>", ME, "Re: Quick question", "Inbox")
        self.assertNotIn("p0@co0.com", run(*blast, reply))

    def test_automated_sender_is_dropped(self):
        found = run(msg(f"Ada <{ME}>", "news@shop.com", "Order", "Sent"),
                    msg("Shop <news@shop.com>", ME, "Deals", "Inbox", "List-Unsubscribe: <mailto:u@shop.com>"))
        self.assertEqual(found, {})

    def test_role_address_is_dropped(self):
        found = run(msg(f"Ada <{ME}>", "registrar@example.edu", "Transcript", "Sent"),
                    msg("Registrar <registrar@example.edu>", ME, "Re: Transcript", "Inbox"))
        self.assertEqual(found, {})

    def test_spam_and_trash_ignored(self):
        found = run(msg(f"Ada <{ME}>", "bob@x.com", "Hi", "Sent"), msg("Bob <bob@x.com>", ME, "Hi", "Spam"))
        self.assertEqual(found, {})


if __name__ == "__main__":
    unittest.main()
