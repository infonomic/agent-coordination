"""coord-check: what is unprocessed, and reconciliation across both crash windows."""
import json, os, tempfile, unittest
from fixtures import helper


def new_mailbox():
    d = tempfile.mkdtemp(prefix="coord-mbox-")
    r = helper("coord-check", "--mailbox", d, "--role", "reviewer", "--init")
    assert r.returncode == 0, r.stderr.decode()
    return d


def body(text=b"b\n"):
    fd, p = tempfile.mkstemp(prefix="coord-body-")
    os.write(fd, text)
    os.close(fd)
    return p


def publish(mbox, frm="implementer", to="reviewer", type="handoff", **kw):
    args = ["--mailbox", mbox, "--from", frm, "--to", to, "--type", type, "--body", body()]
    for k, v in kw.items():
        args += ["--" + k.replace("_", "-"), v]
    r = helper("coord-publish", *args)
    assert r.returncode == 0, r.stderr.decode()
    return r.stdout.decode().strip()


def check(mbox, role="reviewer", *extra):
    return helper("coord-check", "--mailbox", mbox, "--role", role, *extra)


def pending(mbox, role="reviewer"):
    r = check(mbox, role, "--json")
    assert r.returncode == 0, r.stderr.decode()
    return json.loads(r.stdout.decode())


class Initialisation(unittest.TestCase):
    def test_init_creates_the_mailbox_layout(self):
        d = tempfile.mkdtemp(prefix="coord-mbox-")
        helper("coord-check", "--mailbox", d, "--role", "reviewer", "--init")
        for sub in ("messages", "tmp", "state"):
            self.assertTrue(os.path.isdir(os.path.join(d, sub)), sub)


class Pending(unittest.TestCase):
    def setUp(self):
        self.m = new_mailbox()

    def test_lists_a_message_addressed_to_this_role(self):
        mid = publish(self.m)
        self.assertEqual([mid], pending(self.m)["pending"])

    def test_ignores_messages_this_role_authored(self):
        publish(self.m, frm="reviewer", to="implementer", type="review", outcome="approved")
        self.assertEqual([], pending(self.m)["pending"])

    def test_a_recorded_message_is_no_longer_pending(self):
        mid = publish(self.m)
        rid = publish(self.m, frm="reviewer", to="implementer", type="review",
                      outcome="approved", reply_to=mid)
        check(self.m, "reviewer", "--record", mid, "--action", "reviewed", "--response", rid)
        self.assertEqual([], pending(self.m)["pending"])

    def test_pending_order_follows_publication_not_filename_luck(self):
        first = publish(self.m)
        second = publish(self.m, type="status")
        self.assertEqual([first, second], pending(self.m)["pending"])


class CrashWindowActedNotRecorded(unittest.TestCase):
    """Work declared started and never completed: interrupted.

    Note the contract: interruption is *declared*, not inferred from the absence
    of a response. Inferring it mislabels legitimate no-response completions.
    """

    def test_interrupted_action_is_reported_not_silently_repeated(self):
        m = new_mailbox()
        mid = publish(m)
        check(m, "reviewer", "--record", mid, "--action", "reviewing", "--in-progress")
        state = pending(m)
        self.assertIn(mid, [i["message"] for i in state["interrupted"]])
        self.assertNotIn(mid, state["pending"],
                         "an interrupted action must not be re-served as fresh work")


class CrashWindowPublishedNotJournalled(unittest.TestCase):
    """Response reached the mailbox, the session died before the journal was written."""

    def test_orphan_response_is_discovered_and_reconciled(self):
        m = new_mailbox()
        mid = publish(m)
        rid = publish(m, frm="reviewer", to="implementer", type="review",
                      outcome="approved", reply_to=mid)   # journal never updated
        state = pending(m)
        self.assertEqual([], state["pending"],
                         "would have republished a duplicate response")
        self.assertIn(mid, [i["message"] for i in state["reconciled"]])

    def test_reconciliation_is_persisted_to_the_journal(self):
        m = new_mailbox()
        mid = publish(m)
        publish(m, frm="reviewer", to="implementer", type="review",
                outcome="approved", reply_to=mid)
        pending(m)
        with open(os.path.join(m, "state", "reviewer.json")) as f:
            journal = json.load(f)
        self.assertIn(mid, [e["message"] for e in journal["processed"]])


class IntermediateRepliesDoNotComplete(unittest.TestCase):
    def test_a_question_leaves_its_parent_unresolved(self):
        m = new_mailbox()
        mid = publish(m)
        publish(m, frm="reviewer", to="implementer", type="question", reply_to=mid)
        state = pending(m)
        self.assertIn(mid, state["pending"],
                      "asking a clarifying question closed the review it was about")

    def test_a_review_does_complete_its_parent(self):
        m = new_mailbox()
        mid = publish(m)
        publish(m, frm="reviewer", to="implementer", type="review",
                outcome="approved", reply_to=mid)
        self.assertEqual([], pending(m)["pending"])


class CompletionState(unittest.TestCase):
    """Completion is recorded intent, not an inference from whether a reply exists.

    Inferring it from responses mislabels legitimate no-response completions --
    reading a terminal status -- as interrupted, which pressures agents into
    sending acknowledgement replies nobody wants, or into inventing fake response
    ids to silence the tool.
    """

    def test_recording_without_a_response_completes_the_action(self):
        m = new_mailbox()
        mid = publish(m, type="status")
        check(m, "reviewer", "--record", mid, "--action", "read; nothing to answer")
        state = pending(m)
        self.assertEqual([], state["interrupted"])
        self.assertEqual([], state["pending"])

    def test_declaring_work_in_progress_marks_it_interrupted_after_a_crash(self):
        m = new_mailbox()
        mid = publish(m)
        check(m, "reviewer", "--record", mid, "--action", "reviewing", "--in-progress")
        state = pending(m)
        self.assertIn(mid, [i["message"] for i in state["interrupted"]])
        self.assertNotIn(mid, state["pending"])

    def test_an_interruption_completes_when_the_work_finishes(self):
        m = new_mailbox()
        mid = publish(m)
        check(m, "reviewer", "--record", mid, "--action", "reviewing", "--in-progress")
        rid = publish(m, frm="reviewer", to="implementer", type="review",
                      outcome="approved", reply_to=mid)
        check(m, "reviewer", "--record", mid, "--action", "reviewed", "--response", rid)
        state = pending(m)
        self.assertEqual([], state["interrupted"],
                         "an interruption stayed active after the work completed")

    def test_completing_updates_the_entry_rather_than_appending_a_second(self):
        m = new_mailbox()
        mid = publish(m)
        check(m, "reviewer", "--record", mid, "--action", "reviewing", "--in-progress")
        check(m, "reviewer", "--record", mid, "--action", "reviewed", "--response", "r1")
        with open(os.path.join(m, "state", "reviewer.json")) as f:
            journal = json.load(f)
        entries = [e for e in journal["processed"] if e["message"] == mid]
        self.assertEqual(1, len(entries), "history duplicated instead of completing")
        self.assertEqual("completed", entries[0]["state"])
        self.assertEqual(["r1"], entries[0]["responses"])
        self.assertEqual("reviewing", entries[0].get("started_as"),
                         "the original intent was lost instead of preserved")

    def test_reconciliation_completes_an_interrupted_entry(self):
        """The crash window and the interruption are the same message."""
        m = new_mailbox()
        mid = publish(m)
        check(m, "reviewer", "--record", mid, "--action", "reviewing", "--in-progress")
        publish(m, frm="reviewer", to="implementer", type="review",
                outcome="approved", reply_to=mid)      # journal never updated
        state = pending(m)
        self.assertEqual([], state["interrupted"],
                         "a discovered response did not clear the interruption")
        self.assertIn(mid, [i["message"] for i in state["reconciled"]])

    def test_a_completed_entry_never_reopens(self):
        m = new_mailbox()
        mid = publish(m)
        check(m, "reviewer", "--record", mid, "--action", "reviewed", "--response", "r1")
        pending(m)
        state = pending(m)
        self.assertEqual([], state["interrupted"])


class LegacyJournals(unittest.TestCase):
    """Journals written before completion state existed must still be readable."""

    def _legacy(self, responses):
        m = new_mailbox()
        mid = publish(m)
        with open(os.path.join(m, "state", "reviewer.json"), "w") as f:
            json.dump({"last_read": mid,
                       "processed": [{"message": mid, "action": "reviewed",
                                      "responses": responses, "at": "2026-01-01T00:00:00Z"}]}, f)
        return m, mid

    def test_legacy_entry_with_a_response_reads_as_completed(self):
        m, mid = self._legacy(["r1"])
        self.assertEqual([], pending(m)["interrupted"])

    def test_legacy_entry_without_a_response_reads_as_interrupted(self):
        m, mid = self._legacy([])
        self.assertIn(mid, [i["message"] for i in pending(m)["interrupted"]])


class JournalIntegrity(unittest.TestCase):
    def test_journal_survives_repeated_updates_and_stays_parseable(self):
        m = new_mailbox()
        for _ in range(10):
            mid = publish(m)
            check(m, "reviewer", "--record", mid, "--action", "reviewed", "--response", "x")
        with open(os.path.join(m, "state", "reviewer.json")) as f:
            journal = json.load(f)
        self.assertEqual(10, len(journal["processed"]))

    def test_journal_updates_leave_no_staging_residue(self):
        m = new_mailbox()
        mid = publish(m)
        check(m, "reviewer", "--record", mid, "--action", "reviewed", "--response", "x")
        self.assertEqual([], os.listdir(os.path.join(m, "tmp")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
