"""coord-verify: patch drift and environment drift, reported separately."""
import json, os, unittest
from fixtures import commit_all, git, helper, loose_objects, new_repo, write


def snap(repo, base, *scope, mid="m0001", ignored=()):
    extra = []
    for name in ignored:
        extra += ["--ignored-input", name]
    r = helper("coord-snapshot", "--repo", repo, "--run", "testrun",
               "--message-id", mid, "--base", base, "--scope", *scope, *extra)
    assert r.returncode == 0, r.stderr.decode()
    return json.loads(r.stdout.decode())


def verify(repo, s, *scope):
    r = helper("coord-verify", "--repo", repo, "--base", s["base"], "--scope", *scope,
               "--snapshot", s["snapshot"], "--patch-manifest", s["patch_manifest"],
               "--env-manifest", s["env_manifest"], "--head", s["head"])
    return r, json.loads(r.stdout.decode()) if r.stdout.strip() else {}


class BindsToTheSnapshot(unittest.TestCase):
    """A manifest comparison alone does not prove the named snapshot exists."""

    def setUp(self):
        self.r = new_repo()
        write(self.r, "src/a.txt", b"a\n")
        self.base = commit_all(self.r)
        write(self.r, "src/a.txt", b"work\n")
        self.s = snap(self.r, self.base, "src")

    def test_rejects_a_snapshot_id_that_does_not_exist(self):
        fake = dict(self.s, snapshot="0" * 40)
        r, out = verify(self.r, fake, "src")
        self.assertNotEqual(0, r.returncode, "verified against a nonexistent snapshot")

    def test_rejects_a_snapshot_whose_contents_contradict_the_manifest(self):
        write(self.r, "src/a.txt", b"different\n")
        second = snap(self.r, self.base, "src", mid="m0101")
        write(self.r, "src/a.txt", b"work\n")      # worktree back in step with self.s
        clean, _ = verify(self.r, self.s, "src")
        self.assertEqual(0, clean.returncode,
                         "precondition: the working tree still matches the declared manifest")
        crossed = dict(self.s, snapshot=second["snapshot"])
        r, _ = verify(self.r, crossed, "src")
        self.assertNotEqual(0, r.returncode,
                            "accepted a manifest that does not describe the named snapshot")
        self.assertIn(b"does not match the declared patch manifest", r.stderr)

    def test_rejects_a_snapshot_not_descended_from_the_declared_base(self):
        git(self.r, "commit", "-qam", "unrelated")
        elsewhere = git(self.r, "rev-parse", "HEAD").decode().strip()
        stray = snap(self.r, elsewhere, "src", mid="m0102")
        crossed = dict(stray, base=self.base)
        r, out = verify(self.r, crossed, "src")
        self.assertNotEqual(0, r.returncode, "accepted a snapshot built on another base")


class LeavesTheIndexAlone(unittest.TestCase):
    def test_verification_does_not_modify_the_real_index(self):
        import time
        r = new_repo()
        write(r, "src/a.txt", b"a\n")
        base = commit_all(r)                 # clean tree: the index holds a stat cache
        s = snap(r, base, "src")
        index = os.path.join(r, ".git", "index")
        later = time.time() + 5
        os.utime(os.path.join(r, "src/a.txt"), (later, later))  # stat changes, content does not
        with open(index, "rb") as f:
            before = f.read()
        verify(r, s, "src")
        with open(index, "rb") as f:
            after = f.read()
        self.assertEqual(before, after, "the reviewer rewrote the real index")


class Agreement(unittest.TestCase):
    def setUp(self):
        self.r = new_repo()
        write(self.r, "src/a.txt", b"a\n")
        write(self.r, "other/b.txt", b"b\n")
        self.base = commit_all(self.r)
        write(self.r, "src/a.txt", b"work\n")
        self.s = snap(self.r, self.base, "src")

    def test_unchanged_checkout_verifies(self):
        r, out = verify(self.r, self.s, "src")
        self.assertEqual(0, r.returncode, r.stderr.decode())
        self.assertEqual("match", out["patch"])
        self.assertEqual("match", out["environment"])

    def test_patch_drift_is_reported_and_fails(self):
        write(self.r, "src/a.txt", b"moved on\n")
        r, out = verify(self.r, self.s, "src")
        self.assertNotEqual(0, r.returncode)
        self.assertEqual("drift", out["patch"])
        self.assertEqual("match", out["environment"])

    def test_out_of_scope_change_is_environment_drift_not_patch_drift(self):
        write(self.r, "other/b.txt", b"dependency bumped\n")
        r, out = verify(self.r, self.s, "src")
        self.assertNotEqual(0, r.returncode, "verification survived an environment change")
        self.assertEqual("match", out["patch"], "patch wrongly reported as drifted")
        self.assertEqual("drift", out["environment"])

    def test_moved_head_is_environment_drift(self):
        git(self.r, "commit", "-qam", "unrelated commit")
        r, out = verify(self.r, self.s, "src")
        self.assertNotEqual(0, r.returncode)
        self.assertEqual("drift", out["environment"])

    def test_mailbox_activity_is_not_environment_drift(self):
        """The mailbox lives inside the repository. If publishing a message counted
        as an environment change, handing off would invalidate its own review."""
        mbox = os.path.join(self.r, ".coord", "run1")
        helper("coord-check", "--mailbox", mbox, "--role", "implementer", "--init")
        s = snap(self.r, self.base, "src", mid="m0009")
        import tempfile
        fd, b = tempfile.mkstemp(); os.write(fd, b"x\n"); os.close(fd)
        helper("coord-publish", "--mailbox", mbox, "--from", "implementer", "--to",
               "reviewer", "--type", "handoff", "--body", b)
        r, out = verify(self.r, s, "src")
        self.assertEqual("match", out["environment"],
                         "publishing a message invalidated its own review")
        self.assertEqual(0, r.returncode)

    def test_mailbox_is_excluded_even_when_ignored_inputs_are_declared(self):
        mbox = os.path.join(self.r, ".coord", "run2")
        helper("coord-check", "--mailbox", mbox, "--role", "implementer", "--init")
        write(self.r, ".env", b"SECRET=1\n")
        write(self.r, ".gitignore", b".env\n")
        commit_all(self.r, "ignore env")
        # Both sides declare the same inputs: the handshake names them once.
        s = snap(self.r, git(self.r, "rev-parse", "HEAD").decode().strip(), "src",
                 mid="m0200", ignored=(".env",))
        import tempfile
        fd, b = tempfile.mkstemp(); os.write(fd, b"x\n"); os.close(fd)
        helper("coord-publish", "--mailbox", mbox, "--from", "implementer", "--to",
               "reviewer", "--type", "handoff", "--body", b)
        r = helper("coord-verify", "--repo", self.r, "--base", s["base"], "--scope", "src",
                   "--snapshot", s["snapshot"], "--patch-manifest", s["patch_manifest"],
                   "--env-manifest", s["env_manifest"], "--head", s["head"],
                   "--ignored-input", ".env")
        out = json.loads(r.stdout.decode())
        self.assertEqual("match", out["environment"],
                         "declaring an ignored input pulled the mailbox back in")

    def test_verification_writes_no_git_objects(self):
        before = loose_objects(self.r)
        verify(self.r, self.s, "src")
        self.assertEqual(before, loose_objects(self.r))


if __name__ == "__main__":
    unittest.main(verbosity=2)
