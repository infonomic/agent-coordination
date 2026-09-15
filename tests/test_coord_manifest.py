"""coord-manifest: one canonical serializer, two sources."""
import os, unittest
from fixtures import (adversarial_repo, commit_all, git, helper, loose_objects,
                      new_repo, snapshot, symlink, write)


def digest(repo, *args):
    r = helper("coord-manifest", "--repo", repo, *args)
    assert r.returncode == 0, r.stderr.decode()
    return r.stdout.decode().strip()


def tree_digest(repo, rev, *scope):
    return digest(repo, "--source", "tree", "--rev", rev, "--scope", *scope)


def wt_digest(repo, *scope):
    return digest(repo, "--source", "worktree", "--scope", *scope)


class TreeWorktreeAgreement(unittest.TestCase):
    """The two sources must produce identical bytes for identical content."""

    def test_agree_on_a_simple_repository(self):
        r = new_repo()
        write(r, "src/one.txt", b"hello\n")
        base = commit_all(r)
        snap = snapshot(r, base, ["src"])
        self.assertEqual(tree_digest(r, snap, "src"), wt_digest(r, "src"))

    def test_agree_on_the_adversarial_fixtures(self):
        """Newline in filename, symlink target with newline, mode/name ordering
        conflict, and a deleted-but-cached tracked file -- all at once."""
        r = adversarial_repo()
        base = git(r, "rev-parse", "HEAD").decode().strip()
        snap = snapshot(r, base, ["src"])
        self.assertEqual(tree_digest(r, snap, "src"), wt_digest(r, "src"))

    def test_scope_is_honoured_on_both_sides(self):
        r = new_repo()
        write(r, "src/in.txt", b"in\n")
        write(r, "other/out.txt", b"out\n")
        base = commit_all(r)
        snap = snapshot(r, base, ["src"])
        before = wt_digest(r, "src")
        write(r, "other/out.txt", b"changed\n")
        self.assertEqual(before, wt_digest(r, "src"), "out-of-scope edit changed an in-scope manifest")
        self.assertEqual(tree_digest(r, snap, "src"), before)


class DriftSensitivity(unittest.TestCase):
    """Cases a per-file content digest misses."""

    def setUp(self):
        self.r = new_repo()
        write(self.r, "src/f.txt", b"same\n")
        write(self.r, "src/g.txt", b"same\n")
        symlink(self.r, "src/link", b"f.txt")
        commit_all(self.r)
        self.base = wt_digest(self.r, "src")

    def test_executable_bit_change_is_drift(self):
        os.chmod(os.path.join(self.r, "src/f.txt"), 0o755)
        self.assertNotEqual(self.base, wt_digest(self.r, "src"))

    def test_symlink_repointed_between_identical_files_is_drift(self):
        symlink(self.r, "src/link", b"g.txt")
        self.assertNotEqual(self.base, wt_digest(self.r, "src"))

    def test_symlink_trailing_newline_is_significant(self):
        symlink(self.r, "src/link", b"f.txt\n")
        self.assertNotEqual(self.base, wt_digest(self.r, "src"))

    def test_content_change_is_drift(self):
        write(self.r, "src/f.txt", b"different\n")
        self.assertNotEqual(self.base, wt_digest(self.r, "src"))


class FailureBehaviour(unittest.TestCase):
    def test_unreadable_file_aborts_naming_the_path(self):
        r = new_repo()
        write(r, "src/ok.txt", b"ok\n")
        p = write(r, "src/locked.txt", b"secret\n")
        commit_all(r)
        os.chmod(p, 0o000)
        try:
            res = helper("coord-manifest", "--repo", r, "--source", "worktree", "--scope", "src")
            self.assertNotEqual(0, res.returncode, "corrupt manifest reported as success")
            self.assertIn(b"locked.txt", res.stderr)
            self.assertEqual(b"", res.stdout, "emitted a manifest despite failing")
        finally:
            os.chmod(p, 0o644)

    def test_deleted_but_cached_file_is_absent_not_corrupt(self):
        r = new_repo()
        write(r, "src/keep.txt", b"k\n")
        write(r, "src/gone.txt", b"g\n")
        commit_all(r)
        os.remove(os.path.join(r, "src/gone.txt"))
        res = helper("coord-manifest", "--repo", r, "--source", "worktree", "--scope", "src", "--print")
        self.assertEqual(0, res.returncode, res.stderr.decode())
        self.assertNotIn(b"gone.txt", res.stdout)
        self.assertIn(b"keep.txt", res.stdout)

    def test_content_conversion_attributes_are_refused(self):
        r = new_repo()
        write(r, "src/f.txt", b"f\n")
        write(r, ".gitattributes", b"*.txt text=auto\n")
        commit_all(r)
        res = helper("coord-manifest", "--repo", r, "--source", "worktree", "--scope", "src")
        self.assertNotEqual(0, res.returncode, "accepted a repo with content conversion")
        self.assertIn(b"gitattributes", res.stderr.lower())


class DeclaredIgnoredInputs(unittest.TestCase):
    def setUp(self):
        self.r = new_repo()
        write(self.r, "src/f.txt", b"f\n")
        write(self.r, ".gitignore", b".env\n")
        commit_all(self.r)

    def test_missing_input_is_stable_across_runs(self):
        a = wt_digest(self.r, "src", "--ignored-input", ".env")
        b = wt_digest(self.r, "src", "--ignored-input", ".env")
        self.assertEqual(a, b)

    def test_creating_a_missing_input_is_detected(self):
        before = wt_digest(self.r, "src", "--ignored-input", ".env")
        write(self.r, ".env", b"SECRET=1\n")
        self.assertNotEqual(before, wt_digest(self.r, "src", "--ignored-input", ".env"))

    def test_changing_a_present_input_is_detected(self):
        write(self.r, ".env", b"SECRET=1\n")
        before = wt_digest(self.r, "src", "--ignored-input", ".env")
        write(self.r, ".env", b"SECRET=2\n")
        self.assertNotEqual(before, wt_digest(self.r, "src", "--ignored-input", ".env"))


class ReadOnly(unittest.TestCase):
    def test_writes_no_git_objects(self):
        r = adversarial_repo()
        base = git(r, "rev-parse", "HEAD").decode().strip()
        snap = snapshot(r, base, ["src"])
        before = loose_objects(r)
        wt_digest(r, "src")
        tree_digest(r, snap, "src")
        self.assertEqual(before, loose_objects(r))


if __name__ == "__main__":
    unittest.main(verbosity=2)
