"""Fixture builders for coordination helper tests.

Fixtures are built in Python, never shell: command substitution strips trailing
newlines, which silently destroys the symlink-target case these tests exist to cover.
"""
import os, subprocess, tempfile

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")


def run(args, cwd=None, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(args, cwd=cwd, env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def helper(name, *args, cwd=None):
    return run([os.path.join(BIN, name)] + list(args), cwd=cwd)


def git(cwd, *args):
    r = run(["git"] + list(args), cwd=cwd)
    if r.returncode != 0:
        raise AssertionError(f"git {args} failed: {r.stderr.decode()}")
    return r.stdout


def new_repo():
    d = tempfile.mkdtemp(prefix="coord-test-")
    git(d, "init", "-q", ".")
    git(d, "config", "user.email", "test@example.com")
    git(d, "config", "user.name", "Test")
    return d


def write(repo, path, data=b"x\n", mode=None):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(data)
    if mode is not None:
        os.chmod(full, mode)
    return full


def symlink(repo, path, target_bytes):
    """target_bytes preserved exactly, trailing newline included."""
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    if os.path.lexists(full):
        os.remove(full)
    os.symlink(target_bytes, full)
    return full


def commit_all(repo, msg="base"):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)
    return git(repo, "rev-parse", "HEAD").decode().strip()


def snapshot(repo, base, scope):
    """Mint a review snapshot the way coord-snapshot will, for manifest tests."""
    idx = tempfile.mktemp(prefix="coord-idx-")
    env = {"GIT_INDEX_FILE": idx}
    run(["git", "read-tree", base], cwd=repo, env=env)
    run(["git", "add", "-A", "--"] + list(scope), cwd=repo, env=env)
    tree = run(["git", "write-tree"], cwd=repo, env=env).stdout.decode().strip()
    snap = run(["git", "commit-tree", tree, "-p", base, "-m", "snap"], cwd=repo).stdout.decode().strip()
    if os.path.exists(idx):
        os.remove(idx)
    return snap


def loose_objects(repo):
    n = 0
    for root, _, files in os.walk(os.path.join(repo, ".git", "objects")):
        n += len(files)
    return n


def adversarial_repo():
    """The four fixtures that broke the shell algorithm during design review."""
    r = new_repo()
    write(r, "src/a.txt", b"b\n")                       # name sorts before b.txt
    write(r, "src/b.txt", b"a\n", mode=0o755)           # but mode sorts first
    write(r, "src/c.txt", b"c\n")
    write(r, "src/new\nline.txt", b"n\n")               # newline in filename
    symlink(r, "src/oddlink", b"targ\n")                # target ends in a newline
    write(r, "src/gone.txt", b"d\n")                    # deleted below, stays cached
    commit_all(r)
    os.remove(os.path.join(r, "src/gone.txt"))
    return r
