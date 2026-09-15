"""coord-publish: immutable, atomic, non-replacing publication."""
import os, re, tempfile, unittest
from fixtures import helper


def mailbox():
    d = tempfile.mkdtemp(prefix="coord-mbox-")
    for sub in ("messages", "tmp", "state"):
        os.makedirs(os.path.join(d, sub))
    return d


def body_file(text=b"body text\n"):
    fd, p = tempfile.mkstemp(prefix="coord-body-")
    os.write(fd, text)
    os.close(fd)
    return p


def publish(mbox, body, *extra, frm="implementer", to="reviewer", type="handoff"):
    return helper("coord-publish", "--mailbox", mbox, "--from", frm, "--to", to,
                  "--type", type, "--body", body, *extra)


class Publication(unittest.TestCase):
    def setUp(self):
        self.m = mailbox()
        self.b = body_file()

    def test_publishes_a_message_and_reports_its_id(self):
        r = publish(self.m, self.b)
        self.assertEqual(0, r.returncode, r.stderr.decode())
        mid = r.stdout.decode().strip()
        self.assertTrue(os.path.exists(os.path.join(self.m, "messages", mid + ".md")))

    def test_id_carries_timestamp_role_type_and_a_random_suffix(self):
        mid = publish(self.m, self.b).stdout.decode().strip()
        self.assertRegex(mid, r"^\d{8}T\d{6}Z-implementer-handoff-[0-9a-f]{12}$")

    def test_same_second_same_type_ids_are_distinct(self):
        ids = {publish(self.m, self.b).stdout.decode().strip() for _ in range(5)}
        self.assertEqual(5, len(ids), "ids collided within one second")

    def test_body_bytes_are_preserved_verbatim(self):
        b = body_file(b"line\n\ttabbed\nno trailing newline")
        mid = publish(self.m, b).stdout.decode().strip()
        with open(os.path.join(self.m, "messages", mid + ".md"), "rb") as f:
            written = f.read()
        self.assertTrue(written.endswith(b"line\n\ttabbed\nno trailing newline"))

    def test_frontmatter_records_the_envelope(self):
        mid = publish(self.m, self.b, "--reply-to", "abc", "--checkpoint", "1").stdout.decode().strip()
        with open(os.path.join(self.m, "messages", mid + ".md")) as f:
            text = f.read()
        for field in ("id: " + mid, "from: implementer", "to: reviewer",
                      "type: handoff", "reply_to: abc", "checkpoint: 1", "at: "):
            self.assertIn(field, text)

    def test_staging_directory_is_left_clean(self):
        publish(self.m, self.b)
        self.assertEqual([], os.listdir(os.path.join(self.m, "tmp")))


class NeverReplaces(unittest.TestCase):
    """mv silently clobbers; publication must refuse instead."""

    def test_refuses_to_overwrite_an_existing_message(self):
        m = mailbox()
        b = body_file(b"original\n")
        mid = publish(m, b).stdout.decode().strip()
        target = os.path.join(m, "messages", mid + ".md")

        second = body_file(b"replacement\n")
        r = helper("coord-publish", "--mailbox", m, "--from", "implementer",
                   "--to", "reviewer", "--type", "handoff", "--body", second,
                   "--force-id", mid)
        self.assertNotEqual(0, r.returncode, "replaced a published message")
        with open(target) as f:
            self.assertIn("original", f.read())

    def test_a_refused_publish_leaves_no_partial_file(self):
        m = mailbox()
        b = body_file()
        mid = publish(m, b).stdout.decode().strip()
        before = sorted(os.listdir(os.path.join(m, "messages")))
        helper("coord-publish", "--mailbox", m, "--from", "implementer", "--to",
               "reviewer", "--type", "handoff", "--body", b, "--force-id", mid)
        self.assertEqual(before, sorted(os.listdir(os.path.join(m, "messages"))))
        self.assertEqual([], os.listdir(os.path.join(m, "tmp")))


class CrashSafePublication(unittest.TestCase):
    """A crash between link and unlink leaves a staged hard link to the published
    message. Retrying that id must not truncate what is already published."""

    def test_retry_after_an_interrupted_publish_preserves_the_message(self):
        m = mailbox()
        original = body_file(b"the original findings\n")
        mid = publish(m, original).stdout.decode().strip()
        published = os.path.join(m, "messages", mid + ".md")

        os.link(published, os.path.join(m, "tmp", mid + ".md"))   # simulate the crash

        replacement = body_file(b"clobbered\n")
        helper("coord-publish", "--mailbox", m, "--from", "implementer", "--to",
               "reviewer", "--type", "handoff", "--body", replacement, "--force-id", mid)
        with open(published) as f:
            content = f.read()
        self.assertIn("the original findings", content,
                      "a retry truncated an immutable published message")


class Validation(unittest.TestCase):
    def test_unknown_message_type_is_refused(self):
        r = publish(mailbox(), body_file(), type="gossip")
        self.assertNotEqual(0, r.returncode)
        self.assertIn(b"type", r.stderr)

    def test_missing_mailbox_is_refused(self):
        r = publish("/nonexistent/mailbox", body_file())
        self.assertNotEqual(0, r.returncode)

    def test_outcome_is_only_valid_on_a_review(self):
        r = publish(mailbox(), body_file(), "--outcome", "approved", type="handoff")
        self.assertNotEqual(0, r.returncode, "accepted an outcome on a non-review message")

    def test_review_requires_an_outcome(self):
        r = publish(mailbox(), body_file(), type="review")
        self.assertNotEqual(0, r.returncode, "accepted a review with no outcome")


if __name__ == "__main__":
    unittest.main(verbosity=2)
