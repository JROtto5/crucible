"""`crucible demo DIR`: a tiny git repo with one change on a branch, to try a review on in a few minutes.

The change adds page_count() with a test that passes, but the count rounds down, so the last partial page (and
the items on it) can't be reached. The README's quickstart shows a recorded review of exactly this repo."""
import os, subprocess

BASE = {
    "README.md": "# shelf\n\nA small inventory list with paging.\n",
    "shelf.py": '''PAGE_SIZE = 20


def page(items, n, size=PAGE_SIZE):
    """Items on page n (1-based)."""
    start = (n - 1) * size
    return items[start:start + size]
''',
}
TESTS = {
    "test_shelf.py": '''import unittest

from shelf import page


class PageTest(unittest.TestCase):
    def test_first_and_second_page(self):
        items = list(range(45))
        self.assertEqual(page(items, 1), list(range(20)))
        self.assertEqual(page(items, 2), list(range(20, 40)))


if __name__ == "__main__":
    unittest.main()
''',
}
CHANGE = {
    "shelf.py": BASE["shelf.py"] + '''

def page_count(items, size=PAGE_SIZE):
    """How many pages page() needs to show every item (for the "page 2 of N" footer)."""
    return len(items) // size
''',
    "test_shelf.py": TESTS["test_shelf.py"].replace("from shelf import page\n", "from shelf import page, page_count\n").replace(
        '''

if __name__''', '''
    def test_page_count(self):
        self.assertEqual(page_count(list(range(40))), 2)


if __name__'''),
}
DRAFT = """## Title
Add page_count() for the pager footer

## Body
The footer shows "page 2 of N", so the list needs to know how many pages there are. page_count() returns that
for a list and a page size, with a test.

Tested: `python3 -m unittest`
"""
BRANCH = "add-page-count"


def _git(d, *args, extra=None):
    # no inherited GIT_* (GIT_DIR, GIT_AUTHOR_NAME, ...): they would win over the fixed identity below, or point
    # the commands at another repo
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")} | (extra or {})
    subprocess.run(["git", *args], cwd=d, check=True, capture_output=True, text=True, env=env)


def _commit(d, files, msg, when):
    for p, t in files.items():
        with open(os.path.join(d, p), "w", encoding="utf-8") as f:
            f.write(t)
    _git(d, "add", "-A")
    # fixed author and dates: every demo repo has the same commits, so the README's recorded run matches yours
    who = {"NAME": "crucible demo", "EMAIL": "demo@example.invalid", "DATE": when}
    _git(d, "-c", "commit.gpgsign=false", "commit", "-q", "--no-verify", "-m", msg,
         extra={f"GIT_{role}_{k}": v for role in ("AUTHOR", "COMMITTER") for k, v in who.items()})


def make(path):
    """Create the demo repo at path (which must not exist or be empty). -> its absolute path."""
    d = os.path.abspath(path)
    if os.path.exists(d) and os.listdir(d):
        raise FileExistsError(f"{d} exists and is not empty")
    os.makedirs(d, exist_ok=True)
    _git(d, "init", "-q")
    _git(d, "symbolic-ref", "HEAD", "refs/heads/main")      # `init -b` needs git 2.28
    _commit(d, BASE, "shelf: list paging", "2026-01-05T10:00:00+00:00")
    _commit(d, TESTS, "shelf: test page()", "2026-01-05T10:05:00+00:00")
    _git(d, "checkout", "-q", "-b", BRANCH)
    _commit(d, CHANGE, "shelf: add page_count() for the pager footer", "2026-01-06T09:00:00+00:00")
    with open(os.path.join(d, "PR_DRAFT.md"), "w", encoding="utf-8") as f:
        f.write(DRAFT)
    return d
