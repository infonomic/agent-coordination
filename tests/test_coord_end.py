"""coord-end: cleanup follows the declared retention policy."""
import json, os, unittest
from fixtures import commit_all, git, helper, new_repo, write


def repo_with_snapshot():
    r = new_repo()
    write(r, "src/a.txt", b"a\n")
    base = commit_all(r)
    write(r, "src/a.txt", b"b\n")
    out = helper("coord-snapshot", "--repo", r, "--run", "testrun",
                 "--message-id", "m0001", "--base", base, "--scope", "src")
    return r, json.loads(out.stdout.decode())


def refs(repo):
    return git(repo, "for-each-ref", "--format=%(refname)", "refs/coord").decode().split()


class RetentionPolicies(unittest.TestCase):
    def test_keep_refs_retains_the_snapshots(self):
        r, s = repo_with_snapshot()
        out = helper("coord-end", "--repo", r, "--run", "testrun", "--retention", "keep-refs")
        self.assertEqual(0, out.returncode, out.stderr.decode())
        self.assertIn("refs/coord/testrun/m0001", refs(r))

    def test_bundle_archives_snapshots_before_deleting_refs(self):
        r, s = repo_with_snapshot()
        archive = os.path.join(r, "run.bundle")
        out = helper("coord-end", "--repo", r, "--run", "testrun",
                     "--retention", "bundle", "--archive", archive)
        self.assertEqual(0, out.returncode, out.stderr.decode())
        self.assertTrue(os.path.exists(archive), "no bundle written")
        self.assertEqual([], refs(r))
        listed = git(r, "bundle", "list-heads", archive).decode()
        self.assertIn("m0001", listed)

    def test_discard_deletes_refs_and_warns_about_lost_reviewability(self):
        r, s = repo_with_snapshot()
        out = helper("coord-end", "--repo", r, "--run", "testrun", "--retention", "discard")
        self.assertEqual(0, out.returncode, out.stderr.decode())
        self.assertEqual([], refs(r))
        self.assertIn(b"no longer independently reviewable", out.stderr)

    def test_bundle_without_an_archive_path_is_refused(self):
        r, s = repo_with_snapshot()
        out = helper("coord-end", "--repo", r, "--run", "testrun", "--retention", "bundle")
        self.assertNotEqual(0, out.returncode, "deleted refs with nowhere to archive them")
        self.assertIn("refs/coord/testrun/m0001", refs(r))


if __name__ == "__main__":
    unittest.main(verbosity=2)
