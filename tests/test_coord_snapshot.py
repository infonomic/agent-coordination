"""coord-snapshot: a review revision with an identity, minted outside branch history."""
import json, os, unittest
from fixtures import commit_all, git, helper, new_repo, symlink, write


def snap(repo, base, *scope, run="testrun", mid="m0001", extra=()):
    r = helper("coord-snapshot", "--repo", repo, "--run", run, "--message-id", mid,
               "--base", base, "--scope", *scope, *extra)
    assert r.returncode == 0, r.stderr.decode()
    return json.loads(r.stdout.decode())


class LeavesTheBranchAlone(unittest.TestCase):
    def setUp(self):
        self.r = new_repo()
        write(self.r, "src/a.txt", b"a\n")
        self.base = commit_all(self.r)
        write(self.r, "src/a.txt", b"changed\n")
        write(self.r, "src/new.txt", b"new\n")

    def test_head_branch_and_index_are_untouched(self):
        status_before = git(self.r, "status", "--porcelain")
        head_before = git(self.r, "rev-parse", "HEAD")
        snap(self.r, self.base, "src")
        self.assertEqual(head_before, git(self.r, "rev-parse", "HEAD"))
        self.assertEqual(status_before, git(self.r, "status", "--porcelain"))

    def test_snapshot_is_reachable_through_a_retained_ref(self):
        out = snap(self.r, self.base, "src")
        refs = git(self.r, "for-each-ref", "--format=%(refname)", "refs/coord").decode()
        self.assertIn("refs/coord/testrun/m0001", refs)
        git(self.r, "gc", "--prune=now", "-q")
        self.assertEqual(b"commit\n", git(self.r, "cat-file", "-t", out["snapshot"]))

    def test_captures_tracked_edits_and_untracked_additions_in_scope(self):
        out = snap(self.r, self.base, "src")
        listed = git(self.r, "ls-tree", "-r", "--name-only", out["snapshot"]).decode().split()
        self.assertIn("src/a.txt", listed)
        self.assertIn("src/new.txt", listed)


class ScopeDiscipline(unittest.TestCase):
    def test_out_of_scope_edits_are_excluded_and_reported(self):
        r = new_repo()
        write(r, "src/in.txt", b"in\n")
        write(r, "other/out.txt", b"out\n")
        base = commit_all(r)
        write(r, "src/in.txt", b"edited\n")
        write(r, "other/out.txt", b"unrelated user edit\n")
        out = snap(r, base, "src")
        diff = git(r, "diff", "--name-only", base, out["snapshot"]).decode().split()
        self.assertEqual(["src/in.txt"], diff)
        self.assertIn("other/out.txt", out["excluded"])

    def test_gitignored_files_are_not_captured(self):
        r = new_repo()
        write(r, ".gitignore", b"src/secret\n")
        write(r, "src/a.txt", b"a\n")
        base = commit_all(r)
        write(r, "src/secret", b"shh\n")
        out = snap(r, base, "src")
        self.assertNotIn("src/secret", git(r, "ls-tree", "-r", "--name-only", out["snapshot"]).decode())


class MailboxIsNotContent(unittest.TestCase):
    def test_mailbox_is_excluded_from_the_environment_fingerprint(self):
        r = new_repo()
        write(r, "src/a.txt", b"a\n")
        base = commit_all(r)
        mbox = os.path.join(r, ".coord", "run1")
        helper("coord-check", "--mailbox", mbox, "--role", "implementer", "--init")
        write(r, ".coord/run1/messages/some-message.md", b"published\n")
        out = snap(r, base, "src")
        self.assertEqual([], [x for x in out["excluded"] if x.startswith(".coord")],
                         "the mailbox was treated as reviewable content")


class IgnoredInputsDoNotWidenScope(unittest.TestCase):
    def test_declaring_an_ignored_input_does_not_pull_in_the_mailbox(self):
        r = new_repo()
        write(r, "src/a.txt", b"a\n")
        write(r, ".gitignore", b".env\n")
        base = commit_all(r)
        mbox = os.path.join(r, ".coord", "run1")
        helper("coord-check", "--mailbox", mbox, "--role", "implementer", "--init")
        write(r, ".env", b"S=1\n")
        first = snap(r, base, "src", extra=("--ignored-input", ".env"))
        write(r, ".coord/run1/messages/m.md", b"published\n")
        second = snap(r, base, "src", mid="m0002", extra=("--ignored-input", ".env"))
        self.assertEqual(first["env_manifest"], second["env_manifest"],
                         "declaring an ignored input pulled the mailbox into the fingerprint")


class ManifestBinding(unittest.TestCase):
    def test_reports_a_patch_manifest_derived_from_the_snapshot(self):
        r = new_repo()
        write(r, "src/a.txt", b"a\n")
        base = commit_all(r)
        write(r, "src/a.txt", b"b\n")
        out = snap(r, base, "src")
        derived = helper("coord-manifest", "--repo", r, "--source", "tree",
                         "--rev", out["snapshot"], "--scope", "src")
        self.assertEqual(derived.stdout.decode().strip(), out["patch_manifest"])

    def test_environment_fingerprint_carries_head(self):
        r = new_repo()
        write(r, "src/a.txt", b"a\n")
        base = commit_all(r)
        first = snap(r, base, "src")
        write(r, "src/b.txt", b"b\n")
        commit_all(r, "moves HEAD")
        second = snap(r, git(r, "rev-parse", "HEAD").decode().strip(), "src", mid="m0002")
        self.assertNotEqual(first["env_manifest"], second["env_manifest"],
                            "a moved HEAD must change the environment fingerprint")
        self.assertEqual(first["head"], base)


class CaptureStability(unittest.TestCase):
    def test_reports_three_way_agreement(self):
        r = new_repo()
        write(r, "src/a.txt", b"a\n")
        base = commit_all(r)
        write(r, "src/a.txt", b"b\n")
        out = snap(r, base, "src")
        self.assertTrue(out["stable"])
        self.assertEqual(out["patch_manifest"], out["worktree_manifest"])


class Refusals(unittest.TestCase):
    def test_refuses_to_reuse_an_existing_snapshot_ref(self):
        r = new_repo()
        write(r, "src/a.txt", b"a\n")
        base = commit_all(r)
        snap(r, base, "src")
        again = helper("coord-snapshot", "--repo", r, "--run", "testrun",
                       "--message-id", "m0001", "--base", base, "--scope", "src")
        self.assertNotEqual(0, again.returncode, "overwrote an existing snapshot ref")

    def test_refuses_a_repository_with_content_conversion(self):
        r = new_repo()
        write(r, "src/a.txt", b"a\n")
        write(r, ".gitattributes", b"*.txt text=auto\n")
        base = commit_all(r)
        out = helper("coord-snapshot", "--repo", r, "--run", "testrun",
                     "--message-id", "m0001", "--base", base, "--scope", "src")
        self.assertNotEqual(0, out.returncode)


if __name__ == "__main__":
    unittest.main(verbosity=2)
