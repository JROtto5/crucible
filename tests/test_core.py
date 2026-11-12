import atexit, json, os, re, shutil, subprocess, sys, tempfile, time, unittest

# Every temp dir the suite makes (fixture repos, clones, homes, and those of crucible subprocesses through TMPDIR)
# goes under one root that is removed at exit. Each run used to leave ~80 git repos in /tmp, and the pytest check of
# every self-review runs the suite too: 2026-11-07 the tmpfs hit its inode limit with ~16k crucible-* dirs.
def _sweep_stale_roots(base, max_age=7200):
    """atexit doesn't run when a run is killed (a check timeout, SIGKILL), so remove roots earlier runs left behind.
    Only our own prefix, and only old ones: a suite takes seconds, so a 2 h old root isn't a concurrent run's."""
    import glob, time
    for d in glob.glob(os.path.join(base, "crucible-tests-*")):
        try:
            if time.time() - os.path.getmtime(d) > max_age:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


_sweep_stale_roots(tempfile.gettempdir())
_TMP_ROOT = tempfile.mkdtemp(prefix="crucible-tests-")
atexit.register(shutil.rmtree, _TMP_ROOT, True)
tempfile.tempdir = _TMP_ROOT
os.environ["TMPDIR"] = _TMP_ROOT
_TMP_HOME = tempfile.mkdtemp(prefix="crucible-test-home-")
os.environ["CRUCIBLE_HOME"] = _TMP_HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crucible import catalog as C, diff as D, readiness as R, review as V, routing as RT, style as S, util as U  # noqa: E402

# util reads CRUCIBLE_HOME once, at import. If crucible was imported before this module (a probe that imports it and
# then runs the tests), every fixture would land in the user's real ~/.crucible and show up in `crucible stats`
# (2026-11-07 01:24: crucible-repo-*, o__r, t__polish). Stop instead of writing there.
if os.path.realpath(U.HOME) != os.path.realpath(_TMP_HOME):
    raise RuntimeError(f"crucible was imported before the tests set CRUCIBLE_HOME; refusing to write to {U.HOME}")


def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def make_repo(files, branch_files=None, msg="change"):
    d = tempfile.mkdtemp(prefix="crucible-repo-")
    sh(d, "git", "init", "-q", "-b", "main")
    sh(d, "git", "config", "user.email", "t@t"); sh(d, "git", "config", "user.name", "t")
    for p, t in files.items():
        os.makedirs(os.path.dirname(os.path.join(d, p)) or d, exist_ok=True)
        open(os.path.join(d, p), "w").write(t)
    sh(d, "git", "add", "-A"); sh(d, "git", "commit", "-qm", "init")
    if branch_files is not None:
        sh(d, "git", "checkout", "-qb", "fix")
        for p, t in branch_files.items():
            os.makedirs(os.path.dirname(os.path.join(d, p)) or d, exist_ok=True)
            if t is None:
                os.remove(os.path.join(d, p))
            else:
                open(os.path.join(d, p), "w").write(t)
        sh(d, "git", "add", "-A"); sh(d, "git", "commit", "-qm", msg)
    return d


class TestTempRoot(unittest.TestCase):
    def test_suite_temp_dirs_live_under_one_root(self):
        self.assertEqual(tempfile.gettempdir(), _TMP_ROOT)
        self.assertTrue(make_repo({"a": "1"}).startswith(_TMP_ROOT + os.sep))

    def test_stale_roots_from_killed_runs_are_swept(self):
        base = tempfile.mkdtemp()
        old, new, other = (os.path.join(base, n) for n in ("crucible-tests-old", "crucible-tests-new", "someone-else"))
        for d in (old, new, other):
            os.makedirs(d)
        os.utime(old, (0, 0)); os.utime(other, (0, 0))
        _sweep_stale_roots(base)
        self.assertEqual(sorted(os.listdir(base)), ["crucible-tests-new", "someone-else"])


class TestIds(unittest.TestCase):
    def test_stable_across_wording_case(self):
        self.assertEqual(U.stable_id("a.js", "Off-by-one in loop!"), U.stable_id("a.js", "off by one in LOOP"))

    def test_differs_by_file(self):
        self.assertNotEqual(U.stable_id("a.js", "x"), U.stable_id("b.js", "x"))

    def test_collisions_get_suffix(self):
        fs = V.assign_ids([{"file": "a", "title": "same"}, {"file": "a", "title": "same"}])
        self.assertEqual(fs[1]["id"], fs[0]["id"] + "-2")


class TestDiffMath(unittest.TestCase):
    DIFF = """diff --git a/m.js b/m.js
index 1..2 100644
--- a/m.js
+++ b/m.js
@@ -1,3 +1,4 @@
 a
-b
+B
+console.log(x)
 c
\\ No newline at end of file
diff --git a/gone.js b/gone.js
deleted file mode 100644
--- a/gone.js
+++ /dev/null
@@ -1,1 +0,0 @@
-const k = "ghp_abcdefghijklmnopqrstuvwxyz0123"
diff --git a/test/fixtures/keys.js b/test/fixtures/keys.js
--- /dev/null
+++ b/test/fixtures/keys.js
@@ -0,0 +1,2 @@
+// fixture
+const k = "ghp_abcdefghijklmnopqrstuvwxyz0123"
"""

    def test_line_numbers_and_no_newline(self):
        f = D.parse(self.DIFF)[0]
        adds = [(t, n) for h in f["hunks"] for k, t, _o, n in h["lines"] if k == "+"]
        self.assertEqual(adds, [("B", 2), ("console.log(x)", 3)])
        ctx = [t for h in f["hunks"] for k, t, *_ in h["lines"] if k == " "]
        self.assertEqual(ctx, ["a", "c"])          # "\ No newline" is not a line

    def test_deleted_file_path_and_no_scan(self):
        files = D.parse(self.DIFF)
        self.assertTrue(files[1]["deleted"]); self.assertEqual(files[1]["path"], "gone.js")
        hits = D.scan(files)
        self.assertFalse([h for h in hits if h["file"] == "gone.js"])

    def test_fixture_secret_is_medium_debug_is_low(self):
        hits = {(h["file"], h["title"]): h for h in D.scan(D.parse(self.DIFF))}
        self.assertEqual(hits[("test/fixtures/keys.js", "Possible secret in added line")]["severity"], "medium")
        self.assertEqual(hits[("m.js", "Debug statement left in")]["line"], 3)

    def test_chunk_coverage_splits_big_file(self):
        big = "diff --git a/b.js b/b.js\n--- a/b.js\n+++ b/b.js\n" + "".join(
            f"@@ -{i},1 +{i},1 @@\n-x{i}\n+y{i}\n" for i in range(1, 400))
        chunks, unc = D.chunk(D.parse(big), max_chars=2000)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(unc, [])
        self.assertTrue(all(c["files"] == ["b.js"] for c in chunks))

    def test_region_touched(self):
        r = D.changed_old_ranges("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -10,2 +10,3 @@\n x\n+y\n x\n")
        self.assertTrue(D.region_touched(r["a"], 12)); self.assertFalse(D.region_touched(r["a"], 30))

    def test_map_line(self):
        h = D.hunks_old_new("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -5,1 +5,3 @@\n-x\n+y\n+y\n+y\n")["a"]
        self.assertEqual(D.map_line(h, 2), 2); self.assertIsNone(D.map_line(h, 5)); self.assertEqual(D.map_line(h, 10), 12)

    def test_formatting_only(self):
        d = "diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1,1 +1,1 @@\n-foo( x )\n+foo(x)\n@@ -9,1 +9,1 @@\n-a\n+b\n"
        self.assertEqual(D.formatting_only_hunks(D.parse(d)), ["a:1"])


class TestBaseAndDirty(unittest.TestCase):
    def test_default_base_prefers_upstream(self):
        up = make_repo({"a.txt": "1\n"})
        work = tempfile.mkdtemp(prefix="crucible-clone-")
        sh(work, "git", "clone", "-q", up, "c")
        c = os.path.join(work, "c")
        sh(c, "git", "remote", "add", "upstream", up); sh(c, "git", "fetch", "-q", "upstream")
        self.assertEqual(U.default_base(c), "upstream/main")
        sh(c, "git", "remote", "remove", "upstream")
        self.assertEqual(U.default_base(c), "origin/main")

    def test_dirty_ignores_untracked(self):
        d = make_repo({"a.txt": "1\n"})
        open(os.path.join(d, "PR_DRAFT.md"), "w").write("x")
        self.assertFalse(U.is_dirty(d))
        open(os.path.join(d, "a.txt"), "w").write("2\n")
        self.assertTrue(U.is_dirty(d))


class TestReadiness(unittest.TestCase):
    def test_tests_touched(self):
        self.assertEqual(R.tests_touched(["src/a.js"])["status"], "fail")
        self.assertEqual(R.tests_touched(["src/a.js", "test/a.test.js"])["status"], "pass")
        self.assertEqual(R.tests_touched(["README.md"])["status"], "na")

    def test_issue_link(self):
        self.assertEqual(R.linked_issue("Fixes #1234"), 1234)
        self.assertEqual(R.linked_issue("see https://github.com/o/r/issues/77"), 77)
        self.assertIsNone(R.linked_issue("no link here"))

    def test_commit_style_and_changeset(self):
        d = make_repo({"commitlint.config.js": "module.exports={}\n", ".changeset/README.md": "x\n", "a.js": "1\n"},
                      {"a.js": "2\n"}, msg="updated stuff")
        base = U.git(d, "merge-base", "main", "HEAD")
        self.assertEqual(R.commit_style(d, base, ["updated stuff"])["status"], "fail")
        self.assertEqual(R.commit_style(d, base, ["fix(core): handle null"])["status"], "pass")
        self.assertEqual(R.changelog(d, ["a.js"])["status"], "fail")
        self.assertEqual(R.changelog(d, ["a.js", ".changeset/odd-cats.md"])["status"], "pass")

    def test_template_sections(self):
        d = make_repo({".github/PULL_REQUEST_TEMPLATE.md": "## Description\n\n## Testing\n"})
        self.assertEqual(R.check_draft(d, "## Description\nx")["status"], "fail")
        self.assertEqual(R.check_draft(d, "## Description\nx\n## Testing\nnpm test")["status"], "pass")

    def test_template_without_headings(self):
        # quickstart run on itsdangerous: a checklist-only template read "all 0 sections present"
        d = make_repo({".github/pull_request_template.md": "- [ ] Add tests\n- [ ] Add a changelog entry\n"})
        item = R.check_draft(d, "Fixes #1. " + "word " * 50)
        self.assertEqual((item["item"], item["status"]), ("PR description drafted", "pass"))
        self.assertIn("has no section headings to check", item["evidence"])
        self.assertEqual(R.check_draft(d, "Fixes #1.")["status"], "warn")

    def test_template_tracked_but_not_on_disk(self):
        # supabase/supabase #53101: a sparse checkout had no .github/ on disk, and readiness said "no PR template"
        d = make_repo({".github/pull_request_template.md": "## What kind of change\n\n## What is the current behavior\n",
                       "apps/docs/a.mdx": "x\n"})
        sh(d, "git", "sparse-checkout", "set", "apps/docs")
        self.assertFalse(os.path.exists(os.path.join(d, ".github")))
        self.assertEqual(R.template_text(d)[0], ".github/pull_request_template.md")
        item = R.check_draft(d, "## What kind of change\ndocs\n")
        self.assertEqual(item["status"], "fail")
        self.assertIn("What is the current behavior", item["evidence"])

    def test_template_name_any_case_and_location(self):
        for rel in ("Pull_Request_Template.md", "docs/PULL_REQUEST_TEMPLATE.md",
                    ".github/PULL_REQUEST_TEMPLATE/pull_request_template.md"):
            d = make_repo({rel: "## Summary\n"})
            self.assertEqual(R.template_text(d), (rel, "## Summary\n"), rel)
        # .github wins over the root, as on GitHub
        d = make_repo({"pull_request_template.md": "## Root\n", ".github/pull_request_template.md": "## Hub\n"})
        self.assertEqual(R.template_text(d)[0], ".github/pull_request_template.md")
        # falsifiers: near-miss names and other templates are not the PR template
        d = make_repo({".github/pull_request_template.md.bak": "## A\n", ".github/ISSUE_TEMPLATE/bug.md": "## B\n",
                       "src/pull_request_template.md": "## C\n"})
        self.assertEqual(R.template_text(d), (None, ""))
        self.assertEqual(R.check_draft(d, "x" * 300)["status"], "pass")
        # run from a subdirectory of the work tree: listing and reading both resolve against that directory
        d = make_repo({"pkg/.github/pull_request_template.md": "## Sub\n", ".github/pull_request_template.md": "## Top\n"})
        os.remove(os.path.join(d, "pkg/.github/pull_request_template.md"))
        self.assertEqual(R.template_text(os.path.join(d, "pkg")), (".github/pull_request_template.md", "## Sub\n"))
        # a directory that isn't a git repo still works from disk
        d = tempfile.mkdtemp(prefix="crucible-nogit-")
        os.makedirs(os.path.join(d, ".github"))
        open(os.path.join(d, ".github", "PULL_REQUEST_TEMPLATE.md"), "w").write("## X\n")
        self.assertEqual(R.template_text(d)[0], ".github/PULL_REQUEST_TEMPLATE.md")



def _po(entries, refs_at=1):
    """A catalog from (msgid, msgstr, flags) tuples; refs_at shifts every `#:` source line, like a refactor would."""
    out = ['msgid ""', 'msgstr ""', '"Content-Type: text/plain; charset=UTF-8\\n"', ""]
    for i, (mid, mstr, flags) in enumerate(entries):
        if flags == "obsolete":
            out += [f'#~ msgid "{mid}"', f'#~ msgstr "{mstr}"', ""]
            continue
        out.append(f"#: app/ui.py:{refs_at + i}")
        if flags:
            out.append(f"#, {flags}")
        out += [f'msgid "{mid}"', f'msgstr "{mstr}"', ""]
    return "\n".join(out)


FILLER = [(f"Plain label {i}", f"Etiquette {i}", "") for i in range(120)]
OLD_PO = _po(FILLER + [("Open <b>file</b>", "Ouvrir <b>fichier</b", ""),          # broken, and the change fixes it
                       ("See <a href='x'>docs</a>", "Voir <a href='x'>docs<a>", ""),   # broken, only references move
                       ("Saved %s", "Enregistré %s", ""),
                       ("Gone soon", "Bientôt parti", "")])
NEW_PO = _po(FILLER + [("Open <b>file</b>", "Ouvrir <b>fichier</b>", ""),
                       ("See <a href='x'>docs</a>", "Voir <a href='x'>docs<a>", ""),
                       ("Saved %s", "Enregistré %s", ""),
                       ("Brand new", "", ""),
                       ("Saved %d files", "Enregistré %s", "fuzzy"),
                       ("Gone soon", "Bientôt parti", "obsolete")], refs_at=7)


class TestCatalogDigest(unittest.TestCase):
    """A msgmerge refresh is thousands of bookkeeping lines (Lutris #6952: 31 of 33 chunks, $19.45); the digest
    keeps what a reviewer can judge and still shows the entry where that review's real catch was."""

    def _files(self, old, new, path="po/fr.po"):
        repo = make_repo({path: old}, {path: new})
        return repo, D.parse(sh(repo, "git", "diff", "--unified=5", "main..HEAD"))

    def test_parse_entries(self):
        text = ('msgctxt "menu"\nmsgid "File"\nmsgstr "Fichier"\n#, fuzzy\nmsgid "One"\nmsgid_plural "Many"\n'
                'msgstr[0] "Un"\nmsgstr[1] "Plusieurs"\n\n#~ msgid "Old"\n#~ msgstr "Vieux"\n\nmsgid ""\n"wrap"\n'
                '"ped"\nmsgstr "x"\n')
        e = C.parse(text)
        self.assertEqual([x["key"] for x in e], [("menu", "File", None), (None, "One", "Many"), (None, "Old", None),
                                                 (None, "wrapped", None)])
        self.assertEqual(e[1]["strs"], ["Un", "Plusieurs"])            # no blank line between entries 1 and 2
        self.assertTrue(e[1]["fuzzy"]); self.assertFalse(e[0]["fuzzy"])
        self.assertTrue(e[2]["obsolete"]); self.assertEqual((e[3]["start"], e[3]["end"]), (13, 16))

    def test_refresh_is_digested(self):
        repo, files = self._files(OLD_PO, NEW_PO)
        self.assertTrue(C.should_digest(files[0]))
        new_lines = NEW_PO.split("\n")
        got = C.digest_files(files, lambda p: OLD_PO, lambda p: NEW_PO)
        self.assertEqual(got, ["po/fr.po"])
        t = files[0]["text"]
        self.assertNotIn("#: app/ui.py", t)                             # the bookkeeping is gone
        self.assertNotIn("Plain label 5", t)                            # touched plain text: counted, not shown
        self.assertIn('- msgstr "Ouvrir <b>fichier</b"', t)              # the edit, old and new
        self.assertIn('+ msgstr "Ouvrir <b>fichier</b>"', t)
        m = re.search(r"^L(\d+) msgid \"See <a", t, re.M)                 # the Lutris fr.po:2870 shape stays
        self.assertTrue(m, t)
        self.assertIn("See <a", "\n".join(new_lines[int(m.group(1)) - 1:int(m.group(1)) + 2]))  # L is a real line
        self.assertIn('msgid "Saved %s"', t)                            # placeholders can fail at runtime
        self.assertIn("120 touched entries whose translation is unchanged plain text", t)
        self.assertIn("1 touched entries without a translation", t)
        self.assertIn("1 new fuzzy guesses", t); self.assertNotIn("Saved %d files", t)
        self.assertIn("1 entries now obsolete", t)
        self.assertLess(len(t), len(sh(repo, "git", "diff", "main..HEAD")) / 3)

    def test_falsifiers_left_as_a_diff(self):
        from unittest import mock
        # a hand edit to a catalog is small: reviewed as the plain diff it is
        _, small = self._files(OLD_PO, OLD_PO.replace("Ouvrir <b>fichier</b", "Ouvrir <b>fichier</b>"))
        self.assertFalse(C.should_digest(small[0]))
        self.assertEqual(C.digest_files(small, lambda p: OLD_PO, lambda p: NEW_PO), [])
        self.assertIn("@@ -", small[0]["text"])                          # still the raw diff
        # a big change to anything that isn't a catalog is code
        _, code = self._files(OLD_PO, NEW_PO, path="po/fr.py")
        self.assertEqual(C.digest_files(code, lambda p: OLD_PO, lambda p: NEW_PO), [])
        # the opt-out
        _, big = self._files(OLD_PO, NEW_PO)
        with mock.patch.dict(os.environ, {"CRUCIBLE_CATALOG_DIGEST": "0"}):
            self.assertEqual(C.digest_files(big, lambda p: OLD_PO, lambda p: NEW_PO), [])
        self.assertIn("#: app/ui.py", big[0]["text"])

    def test_new_catalog_is_all_edits(self):
        repo = make_repo({"README": "x\n"}, {"po/de.po": NEW_PO})
        files = D.parse(sh(repo, "git", "diff", "--unified=5", "main..HEAD"))
        self.assertTrue(files[0]["added"])
        C.digest_files(files, lambda p: self.fail("no old side for an added file"), lambda p: NEW_PO)
        self.assertIn("translations this change edits (old `-`, new `+`): 124", files[0]["text"])   # header + 123

    def test_threshold_boundary(self):
        # 199 changed lines stay a diff, 200 are digested (added + removed, as the diff counts them)
        def files(n):
            old = "\n".join(f'msgid "s{i}"\nmsgstr "t{i}"\n' for i in range(n)) + "\n"
            new = old.replace('msgstr "t', 'msgstr "u')
            return self._files(old, new)[1]
        self.assertFalse(C.should_digest(files(99)[0]))     # 99 removed + 99 added = 198
        self.assertTrue(C.should_digest(files(100)[0]))     # 200

    def test_cleared_translation_is_an_edit(self):
        old = OLD_PO
        new = OLD_PO.replace('msgstr "Enregistré %s"', 'msgstr ""').replace("app/ui.py:", "app/main.py:")
        _, files = self._files(old, new)
        C.digest_files(files, lambda p: old, lambda p: new)
        self.assertIn('- msgstr "Enregistré %s"', files[0]["text"])
        self.assertIn('+ msgstr ""', files[0]["text"])

    def test_template_lists_new_msgids(self):
        old = _po([(f"Label {i}", "", "") for i in range(120)])
        new = _po([(f"Label {i}", "", "") for i in range(120)] + [("Saved <b>%s</b>", "", "")], refs_at=9)
        _, files = self._files(old, new, path="po/app.pot")
        self.assertEqual(C.digest_files(files, lambda p: old, lambda p: new), ["po/app.pot"])
        t = files[0]["text"]
        self.assertIn("msgids new to this template: 1", t)
        self.assertIn('msgid "Saved <b>%s</b>"', t); self.assertNotIn('msgid "Label 3"', t)
        self.assertNotIn("msgstr", t.split("]\n", 2)[-1])                 # no empty msgstr rows in a template

    def test_long_string_not_cut(self):
        long_fr = "x" * 600 + " <a href='y'>lien<a>"
        old = OLD_PO.replace("Voir <a href='x'>docs<a>", long_fr)
        new = NEW_PO.replace("Voir <a href='x'>docs<a>", long_fr)
        _, files = self._files(old, new)
        C.digest_files(files, lambda p: old, lambda p: new)
        self.assertIn("lien<a>", files[0]["text"])

    def test_long_entries_never_overflow_a_chunk(self):
        # 25 paragraph-length edits made one ~92k block (> the 45k chunk), truncated and left uncovered
        entries = [(f"<b>{i}</b> " + "w" * 1200, f"<b>{i}</b " + "v" * 1200, "") for i in range(120)]
        old, new = _po(entries), _po([(m, s.replace("</b ", "</b> "), f) for m, s, f in entries])
        _, files = self._files(old, new)
        self.assertEqual(C.digest_files(files, lambda p: old, lambda p: new), ["po/fr.po"])
        chunks, uncovered = D.chunk(files)
        self.assertEqual(uncovered, []); self.assertNotIn("truncated", "".join(c["text"] for c in chunks))
        self.assertEqual(sum(c["text"].count("\nL") for c in chunks), 120)
        self.assertTrue(all(c["text"].count("translations this change edits") for c in chunks))  # title per chunk

    def test_absurd_string_cut_visibly(self):
        self.assertTrue(C._show("x" * 4005).endswith("…[5 more chars, open the file]"))
        self.assertEqual(C._show("a\nb"), "a\\nb")

    def test_template_header_edit_shows_both_sides(self):
        hdr = 'msgid ""\nmsgstr ""\n"POT-Creation-Date: {}\\n"\n\n'
        body = "".join(f'#: a.py:{{}}\nmsgid "L{i}"\nmsgstr ""\n\n' for i in range(120))
        old = hdr.format("2026-01-01") + body.format(*range(120))
        new = hdr.format("2026-11-08") + body.format(*range(5, 125))
        _, files = self._files(old, new, path="po/app.pot")
        C.digest_files(files, lambda p: old, lambda p: new)
        t = files[0]["text"]
        self.assertIn('- msgstr "POT-Creation-Date: 2026-01-01\\n"', t)
        self.assertIn('+ msgstr "POT-Creation-Date: 2026-11-08\\n"', t)

    def test_plural_rendered(self):
        old = _po(FILLER) + '\n#: a.py:1\nmsgid "%d file"\nmsgid_plural "%d files"\nmsgstr[0] "%d fichier"\nmsgstr[1] "%d fichier"\n'
        new = _po(FILLER, refs_at=3) + '\n#: a.py:1\nmsgid "%d file"\nmsgid_plural "%d files"\nmsgstr[0] "%d fichier"\nmsgstr[1] "%d fichiers"\n'
        _, files = self._files(old, new)
        C.digest_files(files, lambda p: old, lambda p: new)
        self.assertIn('msgid_plural "%d files"', files[0]["text"])
        self.assertIn('+ msgstr "%d fichiers"', files[0]["text"])

    def test_big_digest_is_split_into_chunks(self):
        entries = [(f"Open <b>file {i}</b>", f"Ouvrir <b>fichier {i}</b", "") for i in range(1500)]
        old, new = _po(entries), _po([(m, s + ">", f) for m, s, f in entries])
        _, files = self._files(old, new)
        C.digest_files(files, lambda p: old, lambda p: new)
        self.assertGreater(len(files[0]["text"]), 45000)
        chunks, uncovered = D.chunk(files)
        self.assertGreater(len(chunks), 1); self.assertEqual(uncovered, [])
        self.assertTrue(all(len(c["text"]) <= 45000 + 2000 for c in chunks), [len(c["text"]) for c in chunks])
        self.assertEqual(sum(c["text"].count("\nL") for c in chunks), 1500)   # every edited entry, once

    def test_run_review_sends_the_digest(self):
        from unittest import mock
        repo = make_repo({"po/fr.po": OLD_PO, "app.py": "x = 1\n"}, {"po/fr.po": NEW_PO, "app.py": "x = 2\n"})
        prompts = []

        def fake(prompt, model, schema, cwd, *a, **kw):
            if "findings" in schema["properties"]:
                prompts.append(prompt)
                return {"summary": "ok", "findings": []}, 0.01
            return {"keep": True, "severity": "low", "method": "read", "actions": "", "evidence": "", "confidence": "high"}, 0
        home = tempfile.mkdtemp(prefix="crucible-home-")
        with mock.patch.object(V, "HOME", home), mock.patch.object(U, "HOME", home), \
                mock.patch.object(V, "claude", fake), mock.patch.dict(os.environ, {"CRUCIBLE_CACHE": os.path.join(home, "c")}):
            d = V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None)
            r = U.read_json(os.path.join(d, "review.json"))
            report = V.report(r, {})
        sent = "\n".join(prompts)
        self.assertIn("is a gettext catalog", sent); self.assertNotIn("#: app/ui.py", sent)
        self.assertIn("+x = 2", sent)                                   # code next to it is still a diff
        self.assertEqual(r["coverage"]["digested"], ["po/fr.po"]); self.assertTrue(r["coverage"]["complete"])
        self.assertIn("catalogs read as a digest of their entries: po/fr.po", report)


class TestCIMatrix(unittest.TestCase):
    # three-mesh-bvh's real node.js.yml: #959 was GREEN locally on three 0.185 and failed CI on 0.159.0
    BVH_WF = ("jobs:\n  build:\n    runs-on: ubuntu-latest\n    strategy:\n      matrix:\n        node-version: [24.x]\n"
              "        three-version: [0.159.0, 0.168.0, latest]\n\n    steps:\n    - run: npm ci\n"
              "    - run: npm install three@${{ matrix.three-version }}\n    - run: npm test\n")

    def bvh_repo(self, installed="0.185.0", workflow=None):
        files = {"package.json": json.dumps({"peerDependencies": {"three": ">= 0.159.0"},
                                             "devDependencies": {"three": "^0.185.0", "@types/node": "^20"}}),
                 ".github/workflows/node.js.yml": workflow or self.BVH_WF, "src/a.js": "1\n"}
        if installed:
            files["node_modules/three/package.json"] = json.dumps({"name": "three", "version": installed})
        return make_repo(files)

    def test_matrix_axes_parsing(self):
        wf = ("strategy:\n  matrix:  # versions\n    django-version:\n      - '4.2'  # LTS\n      - \"5.0\"\n"
              "    os: [ubuntu-latest, macos-latest]\n    include:\n      - django-version: '3.2'\n"
              "    py: ${{ fromJSON(needs.x.outputs.py) }}\n    exp: [\"${{ inputs.v }}\", '1']\n"
              "  fail-fast: false\nother:\n  matrix: ${{ fromJSON(x) }}\n")
        self.assertEqual(R.matrix_axes(wf), {"django-version": ["4.2", "5.0"], "os": ["ubuntu-latest", "macos-latest"],
                                             "exp": ["1"]})
        # indentless block list (dash at the key's indent) and a flow list split over lines
        wf2 = ("    matrix:\n      three-version:\n      - 0.159.0\n      - latest\n      node: [\n        # oldest LTS first\n        18,  # old\n"
               "        20\n      ]\n      include:\n      - three-version: 0.150.0\n    steps: []\n")
        self.assertEqual(R.matrix_axes(wf2), {"three-version": ["0.159.0", "latest"], "node": ["18", "20"]})

    def test_bvh_959_warns_with_untested_versions(self):
        d = self.bvh_repo()
        it = R.ci_matrix(d, ["src/a.js"])
        self.assertEqual(it["status"], "warn", it)
        self.assertIn("three 0.159.0, three 0.168.0;", it["evidence"])
        self.assertIn("three 0.185.0", it["evidence"])
        self.assertIn("`npm install --no-save three@0.159.0`", it["evidence"])
        self.assertNotIn("waive", it["evidence"])  # warn items can't be waived (only fail items are)
        newest_first = self.BVH_WF.replace("[0.159.0, 0.168.0, latest]", "[latest, 0.168.0, 0.159.0]")
        self.assertIn("three@0.159.0`", R.ci_matrix(self.bvh_repo(workflow=newest_first), ["src/a.js"])["evidence"])
        self.assertNotIn("latest", it["evidence"])  # a floating value is the installed release
        sh(d, "git", "checkout", "-qb", "fix"); open(os.path.join(d, "src/a.js"), "w").write("2\n")
        sh(d, "git", "commit", "-qam", "x")
        rep = R.evaluate(d, "o__r", "main", [{"path": "src/a.js", "hunks": []}], offline=True)
        self.assertIn(("CI dependency matrix tried locally", "warn"), [(i["item"], i["status"]) for i in rep["items"]])
        no_install = R.ci_matrix(self.bvh_repo(installed=None), ["test/a.test.js"])  # tests ran on another machine
        self.assertEqual(no_install["status"], "warn")
        self.assertIn("no local install of three", no_install["evidence"])

    def test_falsifiers_stay_quiet(self):
        # the oldest version is the installed one and the rest float: nothing untested
        wf = self.BVH_WF.replace("[0.159.0, 0.168.0, latest]", "['0.159', latest]")
        self.assertEqual(R.ci_matrix(self.bvh_repo(installed="0.159.0", workflow=wf), ["src/a.js"])["status"], "pass")
        # docs-only change, runtime/os axes only (node-version, os: not declared dependencies), one-value axis
        self.assertEqual(R.ci_matrix(self.bvh_repo(), ["README.md"])["status"], "na")
        runtime = "jobs:\n  t:\n    strategy:\n      matrix:\n        node-version: [18, 20, 22]\n        os: [a, b]\n"
        self.assertEqual(R.ci_matrix(self.bvh_repo(workflow=runtime), ["src/a.js"])["status"], "na")
        # a runtime axis is never a package, even when a scoped package shares the name (@sentry/node, node: dep)
        sentry = make_repo({"package.json": json.dumps({"dependencies": {"@sentry/node": "^8", "node": "^20"}}),
                            "node_modules/node/package.json": json.dumps({"version": "20.1.0"}),
                            ".github/workflows/ci.yml": runtime})
        self.assertEqual(R.ci_matrix(sentry, ["src/a.js"])["status"], "na")
        one = self.BVH_WF.replace("[0.159.0, 0.168.0, latest]", "[0.159.0]")
        self.assertEqual(R.ci_matrix(self.bvh_repo(workflow=one), ["src/a.js"])["status"], "na")

    def test_matrix_axes_unterminated_flow_list(self):
        wf = "  matrix:\n    three-version: [0.159.0,\n  steps:\n    - run: x\n    matrix:\n      a: [1, 2]\n"
        self.assertEqual(R.matrix_axes(wf), {"a": ["1", "2"]})  # the broken list is dropped, the next block still read
        dedented = "  matrix:\n    py: ['3.10',\n# 3.11 is flaky upstream\n      '3.12']\n"  # a column-0 comment isn't the end
        self.assertEqual(R.matrix_axes(dedented), {"py": ["3.10", "3.12"]})

    def test_oldest_per_dependency(self):
        d = make_repo({"package.json": json.dumps({"devDependencies": {"three": "^0.185.0"}}),
                       "requirements.txt": "Django\n",
                       "node_modules/three/package.json": json.dumps({"version": "0.185.0"}),
                       ".github/workflows/ci.yml": "jobs:\n  t:\n    strategy:\n      matrix:\n"
                                                   "        three-version: [latest, 0.168.0, 0.159.0]\n"
                                                   "        django-version: ['3.10', '3.9']\n"})
        ev = R.ci_matrix(d, ["src/a.js"])["evidence"]
        self.assertIn("(`npm install --no-save three@0.159.0`; `pip install 'Django==3.9'`)", ev)  # 3.9 < 3.10
        self.assertIn("local checks used three 0.185.0", ev)

    @unittest.skipIf(sys.version_info < (3, 11), "pyproject is read with tomllib (3.11+)")
    def test_pyproject_dependency(self):
        d = make_repo({"pyproject.toml": "[project]\nname = 'x'\ndependencies = ['numpy>=1.24']\n"
                                         "[project.optional-dependencies]\ndev = ['pytest']\n",
                       ".github/workflows/ci.yml": "jobs:\n  t:\n    strategy:\n      matrix:\n"
                                                   "        numpy-version: ['1.24', '2.1']\n",
                       "x.py": "1\n"})
        self.assertEqual(set(R.declared_deps(d)), {"numpy", "pytest"})
        it = R.ci_matrix(d, ["x.py"])
        self.assertEqual(it["status"], "warn")
        self.assertIn("pip install 'numpy==1.24'", it["evidence"])

    def test_python_dependency_axis(self):
        d = make_repo({"requirements-dev.txt": "# dev\nDjango>=4.2\n-e .\n",
                       ".github/workflows/ci.yml": "jobs:\n  t:\n    strategy:\n      matrix:\n"
                                                   "        python-version: ['3.10', '3.13']\n"
                                                   "        django-version: ['4.2', '5.0']\n",
                       ".venv/lib/python3.13/site-packages/django-5.0.1.dist-info/METADATA": "x\n",
                       "app/views.py": "x = 1\n"})
        it = R.ci_matrix(d, ["app/views.py"])
        self.assertEqual(it["status"], "warn", it)
        self.assertIn("Django 4.2;", it["evidence"])
        self.assertNotIn("5.0;", it["evidence"])  # 5.0.1 installed covers 5.0
        self.assertIn("pip install 'Django==4.2'", it["evidence"])


class TestDraftSplit(unittest.TestCase):
    # shaped like a real draft: metadata preamble, Title/Body sections, then the author's notes after a rule
    NOTED = ("# PR draft (not opened, not pushed)\n\n> Before opening, file the issue at the bottom; see #999.\n\n"
             "## Title\n\n`fix(postgrest): send Date args as ISO 8601`\n\n## Body\n\n## 🔍 Description\n\n"
             "Fixes #42.\n\n```md\n## Explain it to me\n```\n\nTested with `npm test`.\n\n---\n\n"
             "## Explain it to me (Q&A prep)\n\n" + "- why? because. " * 300 + "\n\n## Issue to file first\n\nBody #7\n")

    def test_split_noted_draft(self):
        d = R.split_draft(self.NOTED)
        self.assertEqual(d["title"], "fix(postgrest): send Date args as ISO 8601")
        self.assertTrue(d["body"].startswith("## 🔍 Description"), d["body"][:40])
        self.assertIn("## Explain it to me\n```", d["body"])  # a heading inside a code fence is not a boundary
        self.assertTrue(d["body"].endswith("Tested with `npm test`."), d["body"][-40:])
        self.assertTrue(d["notes"].startswith("# PR draft (not opened, not pushed)"))  # preamble kept as notes
        self.assertIn("\n\n## Explain it to me (Q&A prep)", d["notes"])
        self.assertIn("## Title\n\n`fix(postgrest)", d["notes"])
        self.assertNotIn("## Body", d["notes"])
        self.assertNotIn("#999", d["body"])

    def test_plain_drafts_unchanged(self):
        d = R.split_draft("# WebGPUBackend: Fix timestamps.\n\n**Description**\n\nFixes #1.\n")
        self.assertEqual((d["title"], d["notes"]), ("WebGPUBackend: Fix timestamps.", ""))
        self.assertEqual(d["body"], "\n**Description**\n\nFixes #1.\n".strip("\n"))
        self.assertEqual(R.split_draft("just a body\n\n## Out of scope\nfollow-up")["notes"], "")
        self.assertEqual(R.split_draft("body\n<!-- crucible: notes -->\nmine")["notes"], "mine")

    def test_nested_fences_and_notes_before_body(self):
        tilde = "# T\n\n~~~\n```\n~~~\n\n## Explain it to me\nprivate\n"
        self.assertEqual(R.split_draft(tilde)["notes"], "## Explain it to me\nprivate")
        four = "# T\n\n````md\n```md\n## Explain it to me\n```\n````\nreal body end\n"
        d = R.split_draft(four)
        self.assertEqual(d["notes"], "")
        self.assertTrue(d["body"].endswith("real body end"))
        pre = "# Draft\n\n> file the issue first\n\n## Body\nFixes #5.\n\n## Explain it to me\nx\n"
        d = R.split_draft(pre)
        self.assertEqual((d["title"], d["body"]), ("", "Fixes #5."))  # an H1 above `## Body` is a label, not the title
        self.assertEqual(d["notes"], "# Draft\n\n> file the issue first\n\n## Explain it to me\nx")  # preamble kept

    def test_body_heading_inside_notes_is_ignored(self):
        t = "# T\n\nReal body, Fixes #3.\n\n## Issue to file first\n\n## Title\nbug\n\n## Body\nissue text #9\n"
        d = R.split_draft(t)
        self.assertEqual((d["title"], d["body"]), ("T", "Real body, Fixes #3."))
        self.assertEqual(R.linked_issue(R.submitted_text(t)), 3)

    def test_notes_heading_must_open_the_heading(self):
        body = "# T\n\n## Handling the DO NOT SUBMIT lint marker\nx\n\n### Why not an issue to file later?\ny\n"
        self.assertEqual(R.split_draft(body)["notes"], "")
        d = R.split_draft("# T\n\nb\n\n## 📝 Explain it to me\nn\n")
        self.assertEqual((d["notes"], d["notes_line"]), ("## 📝 Explain it to me\nn", 5))

    def test_inline_triple_backticks_dont_open_a_fence(self):
        d = R.split_draft("# T\n\n```foo``` is now handled.\n\n## Explain it to me\nprivate\n")
        self.assertEqual(d["notes"], "## Explain it to me\nprivate")

    def test_preamble_above_title_without_body_heading(self):
        d = R.split_draft("# PR draft\n\n> file the issue first\n\n## Title\nfix: y\n\nBody.\n")
        self.assertEqual((d["title"], d["body"]), ("fix: y", "Body."))
        self.assertEqual(d["notes"], "# PR draft\n\n> file the issue first")

    def test_title_section_without_body_heading(self):
        d = R.split_draft("## Title\nfix: timestamps\n\n## Summary\nFixes #1.\n")
        self.assertEqual((d["title"], d["body"]), ("fix: timestamps", "## Summary\nFixes #1."))

    def test_notes_dont_drive_findings(self):
        style = {"body": {"median_words": 60, "pct_with_emoji": 50, "pct_with_headings": 60,
                          "common_headings": ["description"]}}
        self.assertIn("length", {k for k, _ in S.ai_tells(self.NOTED, style)})  # the old behaviour
        self.assertEqual(S.ai_tells(R.submitted_text(self.NOTED), style), [])
        self.assertEqual(R.linked_issue(R.submitted_text(self.NOTED)), 42)

    def test_template_headings_allowed(self):
        style = {"body": {"median_words": 400, "pct_with_emoji": 50, "pct_with_headings": 40,
                          "common_headings": ["description", "breaking changes"]}}
        body = "## 🔍 Description\nx\n## 📸 Screenshots/Examples\nx\n## 🔄 Breaking changes\nno\n## 📋 Checklist\n- [x]\n" \
               "## 📝 Additional notes\nnone\n"
        self.assertIn("headings", {k for k, _ in S.ai_tells(body, style)})
        tpl = ["🔍 Description", "📸 Screenshots/Examples", "🔄 Breaking changes", "📋 Checklist", "📝 Additional notes"]
        self.assertEqual(S.ai_tells(body, style, tpl), [])
        self.assertEqual(S.norm_heading("🔄 Breaking changes:"), "breaking changes")
        # a template alone is no evidence that other headings are unusual
        self.assertEqual(S.ai_tells("## A\n## B\n## C\n", {}, ["Description"]), [])

    def test_style_check_uses_template_and_submitted_part(self):
        tpl = "## 🔍 Description\n\n## 📸 Screenshots\n\n## 🔄 Breaking changes\n\n## 📋 Checklist\n"
        d = make_repo({".github/PULL_REQUEST_TEMPLATE.md": tpl})
        style = {"body": {"median_words": 60, "pct_with_emoji": 50, "pct_with_headings": 60, "common_headings": ["testing"]}}
        draft = ("# Fix a\n\n## 🔍 Description\nFixes #1, tested with npm test.\n\n## 📸 Screenshots\nnone\n\n"
                 "## 🔄 Breaking changes\nnone\n\n## 📋 Checklist\n- [x] tests\n\n## Explain it to me\n" + "why " * 500)
        kinds = {x["title"] for x in S.check(d, "HEAD", [], "PR_DRAFT.md", R.submitted_text(draft), style)}
        self.assertEqual(kinds, set())
        self.assertTrue(S.check(d, "HEAD", [], "PR_DRAFT.md", draft, style))  # the raw file would be flagged

    def test_evaluate_reads_only_the_submitted_part(self):
        d = make_repo({"a.js": "1\n"}, {"a.js": "2\n"})
        open(os.path.join(d, "PR_DRAFT.md"), "w").write(
            "# Fix a\n\nShort body, tested with npm test.\n\n## Explain it to me\nsee #77 for history\n")
        base = U.git(d, "merge-base", "main", "HEAD")
        files = D.parse(U.git(d, "diff", f"{base}..HEAD"))
        out = R.evaluate(d, "t__evaluate", base, files, offline=True)
        self.assertIsNone(out["issue"])  # #77 is in the author's notes, not the PR
        self.assertIn({"item": "no open PR changes the same lines", "status": "na", "evidence": "offline"}, out["items"])
        with open(os.path.join(d, "PR_DRAFT.md"), "w") as fh:
            fh.write("# Fix a\n\nFixes #12.\n\n## Explain it to me\nsee #77\n")
        self.assertEqual(R.evaluate(d, "t__evaluate", base, files, offline=True)["issue"], 12)
        with open(os.path.join(d, "PR_DRAFT.md"), "w") as fh:
            fh.write("## Author notes\nx\n\n## Body\nFixes #1.\n")
        item = R.evaluate(d, "t__evaluate", base, files, offline=True)["items"][0]
        self.assertEqual(item["status"], "fail")
        self.assertIn("author-notes boundary at line 1", item["evidence"])

    def test_polish_keeps_notes_once(self):
        d = make_repo({"a.js": "1\n"})
        with open(os.path.join(d, "PR_DRAFT.md"), "w") as fh:
            fh.write("# Fix a\n\nThis PR introduces a fix.\n\n## Explain it to me\nwhy: because\n")
        seen, orig = [], S.claude

        def fake(prompt, *a, **k):
            seen.append(prompt)
            return {"title": "Fix a", "body": "Fix a.", "removed": [], "kept_facts": []}, 0.0
        S.claude = fake
        try:
            for _ in range(3):  # re-polishing must not duplicate the notes marker
                S.polish(d, "t__polish", log=lambda *_: None)
        finally:
            S.claude = orig
        txt = open(os.path.join(d, "PR_DRAFT.polished.md")).read()
        self.assertEqual(txt.count(R.NOTES_MARKER), 1, txt)
        self.assertTrue(txt.rstrip().endswith("## Explain it to me\nwhy: because"), txt)
        self.assertNotIn("why: because", seen[0])  # notes are never sent to be folded into the body
        self.assertEqual(R.split_draft(txt)["body"], "Fix a.")


class TestReviewLogic(unittest.TestCase):
    def test_honesty_caps(self):
        f = V.apply_honesty({"severity": "critical", "caused_by_this_change": False, "reachable_in_real_use": True})
        self.assertEqual(f["severity"], "low"); self.assertEqual(f["capped_from"], "critical")

    def test_dedupe_same_root_cause(self):
        a = {"file": "a.js", "line": 10, "title": "Off by one in loop bound", "severity": "important", "source": "review"}
        b = {"file": "a.js", "line": 11, "title": "Loop bound off by one", "severity": "critical", "source": "review"}
        out = V.dedupe([a, b])
        self.assertEqual(len(out), 1); self.assertEqual(out[0]["severity"], "critical")

    def test_author_model_switch(self):
        d = make_repo({"a.js": "1\n"}, {"a.js": "2\n"},
                      msg="fix\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>")
        os.environ.pop("CRUCIBLE_REVIEW_MODEL", None); os.environ.pop("CRUCIBLE_VERIFY_MODEL", None)
        base = U.git(d, "merge-base", "main", "HEAD")
        rv, vf, au = V.choose_models(d, base)
        self.assertIn("claude-sonnet-5-5", au); self.assertNotEqual(rv, "claude-sonnet-5-5"); self.assertNotEqual(vf, rv)

    def test_verdict_requires_answers_coverage_and_checks(self):
        rev = {"status": "done", "findings": [{"id": "X", "severity": "medium"}], "coverage": {"complete": True},
               "checks": {"results": []}}
        self.assertEqual(V.verdict(rev, {})[0], "NOT_GREEN")
        self.assertEqual(V.verdict(rev, {"X": {"disposition": "deferred"}})[0], "GREEN")
        rev["coverage"]["complete"] = False
        self.assertEqual(V.verdict(rev, {"X": {"disposition": "deferred"}})[0], "NOT_GREEN")
        rev["coverage"]["complete"] = True
        rev["checks"]["results"] = [{"status": "fail"}]
        self.assertEqual(V.verdict(rev, {"X": {"disposition": "deferred"}})[0], "NOT_GREEN")
        rev["checks"]["results"] = [{"status": "fail", "on_base": "fail"}]   # pre-existing failure does not block
        self.assertEqual(V.verdict(rev, {"X": {"disposition": "deferred"}})[0], "GREEN")
        rev["findings"] = [{"id": "Y", "severity": "important"}]
        self.assertEqual(V.verdict(rev, {"Y": {"disposition": "deferred"}})[0], "NOT_GREEN")

    def test_carry_forward(self):
        d = make_repo({"a.js": "".join(f"line{i}\n" for i in range(1, 60))},
                      {"a.js": "".join(f"line{i}\n" for i in range(1, 60)).replace("line5\n", "LINE5\n")})
        proj = U.project_key(d)
        prev = U.git(d, "rev-parse", "HEAD")
        pd = U.review_dir(proj, prev)
        f_near = {"id": "CR-aaaa", "file": "a.js", "line": 40, "title": "t", "severity": "medium"}
        f_far = {"id": "CR-bbbb", "file": "a.js", "line": 6, "title": "u", "severity": "medium"}
        U.write_json(os.path.join(pd, "review.json"), {"status": "done", "findings": [f_near, f_far]})
        U.write_json(os.path.join(pd, "answers.json"), {"CR-aaaa": {"disposition": "refuted", "note": "n"},
                                                         "CR-bbbb": {"disposition": "refuted", "note": "n"}})
        U.write_json(os.path.join(U.project_dir(proj), "branches.json"), {"fix": [prev]})
        open(os.path.join(d, "a.js"), "a").write("")
        txt = open(os.path.join(d, "a.js")).read().replace("line7\n", "LINE7\n")
        open(os.path.join(d, "a.js"), "w").write(txt)
        sh(d, "git", "commit", "-qam", "touch line 7")
        new = U.git(d, "rev-parse", "HEAD")
        rec = {"findings": [dict(f_near), dict(f_far)]}
        V.carry_forward(d, proj, new, rec)
        ans = U.read_json(os.path.join(U.review_dir(proj, new), "answers.json"))
        self.assertIn("CR-aaaa", ans)          # line 40 untouched → carried
        self.assertNotIn("CR-bbbb", ans)       # line 6 is within 3 of touched line 7 → re-answer


class TestStyle(unittest.TestCase):
    def test_median_and_density(self):
        self.assertEqual(S.median_int([10, 30, 20]), 20)
        self.assertEqual(S.median_int([]), None)
        self.assertEqual(S.comment_density("// a\nx\ny\n// b\n"), 50.0)
        self.assertEqual(S.comment_density("#include <x>\nint a;\n"), 0.0)

    def test_body_stats(self):
        st = S.body_stats(["Fixed #12.\n\nShort body here.", "Related issue: #9\n\n## Description\nx", "Fixed #3"])
        self.assertEqual(st["median_words"], 5)
        self.assertIn("fixed #N", st["issue_ref_forms"])
        self.assertIn("related issue: #N", st["issue_ref_forms"])

    def test_ai_tells(self):
        style = {"body": {"median_words": 40, "pct_with_emoji": 0, "pct_with_headings": 10, "common_headings": []}}
        bad = ("## Summary\n🚀 This PR introduces a robust, seamless fix. It's worth noting it leverages best practices.\n"
               "## Changes\n" + "\n".join(f"- item {i}" for i in range(15)) + "\n" + "word " * 200)
        kinds = {k for k, _ in S.ai_tells(bad, style)}
        self.assertTrue({"emoji", "boilerplate", "filler", "bullet bloat", "length", "headings"} <= kinds, kinds)
        good = "Fixes #123.\n\n`WebGLRenderer` leaked the shadow map on resize. Dispose it in `setSize()`.\n\nTested with `npm test`."
        self.assertEqual(S.ai_tells(good, style), [])

    def test_obvious_comment(self):
        self.assertTrue(S.OBVIOUS_COMMENT_RX.match("  // increment the counter"))
        self.assertFalse(S.OBVIOUS_COMMENT_RX.match("  // must run before the depth prepass: see #2213"))


class TestReindentedLines(unittest.TestCase):
    """three-mesh-bvh bvh-errors (2026-11-06): wrapping a worker body in `try {` re-indented a 2024 comment, and the
    house check flagged it as "Comment narrates the obvious"; the author refuted it with `git blame -w`. Lines that
    only re-add a removed line with new indentation are not the author's, so the style checks and the debug scanner
    skip them. Secrets and conflict markers are still checked on every added line."""
    BODY = ["// initialize the number of workers balanced for a binary tree",
            "const n = Math.pow( 2, Math.floor( Math.log2( maxWorkers ) ) );",
            "console.log( 'workers', n );",
            "const tokenHint = 'ghp_abcdefghijklmnopqrstuvwxyz0123';"] + [f"step{i}( n );" for i in range(8)]

    def files(self, wrapped_extra=()):
        base = "function run( maxWorkers ) {\n" + "".join(f"\t{l}\n" for l in self.BODY) + "}\n"
        new = ("function run( maxWorkers ) {\n\ttry {\n" + "".join(f"\t\t{l}\n" for l in self.BODY)
               + "".join(f"\t\t{l}\n" for l in wrapped_extra) + "\t} catch ( e ) {\n\t\treject( e );\n\t}\n}\n")
        d = make_repo({"src/worker.js": base}, {"src/worker.js": new})
        return d, D.parse(sh(d, "git", "diff", "main", "fix"))

    def test_authored_added_skips_reindented_lines(self):
        _d, files = self.files()
        got = [t.strip() for h in files[0]["hunks"] for _n, t in D.authored_added(h)]
        self.assertEqual(got, ["try {", "} catch ( e ) {", "reject( e );", "}"])

    def test_reindented_comment_and_debug_are_not_flagged(self):
        d, files = self.files()
        titles = {x["title"] for x in S.check(d, "main", files, "PR_DRAFT.md", "", {})}
        self.assertFalse(titles & {"Comment narrates the obvious", "Over-commented compared with this file"}, titles)
        hits = {h["title"] for h in D.scan(files)}
        self.assertNotIn("Debug statement left in", hits)
        self.assertIn("Possible secret in added line", hits)     # still caught on a re-indented line

    def test_new_lines_inside_the_wrapped_block_are_still_checked(self):
        extra = ["// initialize the retry counter", "console.log( 'done' );"] + [f"more{i}();" for i in range(8)]
        d, files = self.files(extra)
        found = {(x["title"], x["line"]) for x in S.check(d, "main", files, "PR_DRAFT.md", "", {})}
        self.assertIn(("Comment narrates the obvious", 15), found)
        self.assertIn(("Debug statement left in", 16), {(h["title"], h["line"]) for h in D.scan(files)})

    def test_a_line_removed_once_matches_one_readd(self):
        h = D.parse("diff --git a/a.js b/a.js\n--- a/a.js\n+++ b/a.js\n@@ -1,1 +1,2 @@\n"
                    "-console.log(x)\n+  console.log(x)\n+  console.log(x)\n")[0]["hunks"][0]
        self.assertEqual(D.authored_added(h), [(2, "  console.log(x)")])



class TestRealHomeGuard(unittest.TestCase):
    """2026-11-07 01:24: fixtures leaked into ~/.crucible because crucible was imported (with the real home) before
    this module set CRUCIBLE_HOME. The module now refuses to load in that order and loads normally otherwise."""
    def load(self, code):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = {**os.environ, "CRUCIBLE_HOME": tempfile.mkdtemp(prefix="crucible-guard-home-")}
        return subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True,
                              timeout=60)

    def test_refuses_when_crucible_was_imported_first(self):
        r = self.load("import crucible.util, tests.test_core")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing to write", r.stderr)

    def test_loads_when_imported_first(self):
        r = self.load("import tests.test_core")
        self.assertEqual((r.returncode, r.stderr), (0, ""))


class TestLearnedDataVersion(unittest.TestCase):
    """umu's style.json kept a Dependabot-polluted 879-word median after bug j was fixed, because nothing re-ran
    `learn`. Learned files are stamped with the `learn` version, and readiness says what an older file misses."""
    def write(self, project, fname, data):
        with open(os.path.join(U.project_dir(project), fname), "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))

    def bumped(self, affects):
        """LEARN_VERSION + 1 with a change that affects `affects`, restored on cleanup."""
        orig = (U.LEARN_VERSION, U.LEARN_CHANGES)
        self.addCleanup(lambda: (setattr(U, "LEARN_VERSION", orig[0]), setattr(U, "LEARN_CHANGES", orig[1])))
        U.LEARN_VERSION, U.LEARN_CHANGES = orig[0] + 1, {**orig[1], orig[0] + 1: ("a later fix", affects)}
        return orig[0]

    def test_not_learned(self):
        self.assertEqual(R.learned_data("lv__none")["status"], "na")

    def test_unstamped_files_may_be_missing_what_affects_them(self):
        self.write("lv__old", "meta.json", {"learned": "2026-11-04", "median_merged_pr_lines": 40})
        self.write("lv__old", "style.json", {"body": {"median_words": 879}})
        it = R.learned_data("lv__old")
        self.assertEqual(it["status"], "warn")
        meta, style = it["evidence"].split(" · ")
        self.assertTrue(meta.startswith("meta.json (unstamped, learned 2026-11-04) may be missing: "), meta)
        self.assertTrue(style.startswith("style.json (unstamped) may be missing: "), style)
        for what, affects in U.LEARN_CHANGES.values():
            self.assertEqual(what in meta, "meta.json" in affects)
            self.assertEqual(what in style, "style.json" in affects)
        self.assertIn("Re-run `crucible learn`", it["evidence"])

    def test_stamped_file_lists_only_later_changes_to_itself(self):
        cur = self.bumped(("style.json",))
        self.write("lv__v", "style.json", {"learn_version": cur, "learned": "2026-11-07"})
        self.write("lv__v", "meta.json", {"learn_version": cur})  # the bump doesn't touch meta.json: still current
        it = R.learned_data("lv__v")
        self.assertEqual(it["status"], "warn")
        self.assertTrue(it["evidence"].startswith(f"style.json (v{cur}, learned 2026-11-07) is missing: a later fix."),
                        it["evidence"])
        self.assertNotIn("meta.json", it["evidence"])
        for what, _ in U.LEARN_CHANGES.values():
            self.assertEqual(what in it["evidence"], what == "a later fix")

    def test_current_stamp_passes_and_a_bump_makes_it_stale(self):
        self.write("lv__cur", "style.json", {"learn_version": U.LEARN_VERSION})
        self.write("lv__cur", "meta.json", {"learn_version": U.LEARN_VERSION})
        self.assertEqual(R.learned_data("lv__cur")["status"], "pass")
        self.bumped(("meta.json", "style.json"))  # falsifier: the same files are stale after a later `learn` fix
        it = R.learned_data("lv__cur")
        self.assertEqual((it["status"], it["evidence"].count("a later fix")), ("warn", 2))

    def test_unreadable_or_odd_stamps_count_as_unstamped(self):
        self.write("lv__bad", "style.json", "{not json")
        self.write("lv__bad", "meta.json", {"learn_version": True})
        it = R.learned_data("lv__bad")
        self.assertEqual(it["status"], "warn")
        self.assertIn("meta.json (unstamped) may be missing", it["evidence"])
        self.assertIn("style.json (unstamped) may be missing", it["evidence"])

    def test_every_version_says_what_changed_and_where(self):
        self.assertEqual(sorted(U.LEARN_CHANGES), list(range(2, U.LEARN_VERSION + 1)))
        for what, affects in U.LEARN_CHANGES.values():
            self.assertTrue(what and affects and set(affects) <= {"meta.json", "style.json"})

    def test_run_learn_stamps_meta(self):
        from crucible import learn as L
        repo = make_repo({"a.py": "x = 1\n"})
        sh(repo, "git", "remote", "add", "origin", "https://github.com/o/lv.git")
        orig = (L.collect, L.docs_text)
        L.collect, L.docs_text = (lambda slug, n, log: ([], [], [(10, 4), (20, None)])), (lambda slug: "")
        try:
            meta = L.run_learn(repo, style=False, log=lambda *_: None)
        finally:
            L.collect, L.docs_text = orig
        self.assertEqual(meta["learn_version"], U.LEARN_VERSION)
        self.assertEqual(R.learned_data(U.project_key(repo))["status"], "pass")


class TestSizeNorm(unittest.TestCase):
    """90 stored upstream rounds warned or failed "size vs project norm", many on test lines: colyseus/schema's
    300-line drafts were 234 lines of tests, waived in every round with that reason. Size is judged outside tests."""
    @staticmethod
    def changed(path, n):
        return {"path": path, "hunks": [{"lines": [("+", "x", None, i) for i in range(n)]}]}

    def meta(self, project, **m):
        with open(os.path.join(U.project_dir(project), "meta.json"), "w") as fh:
            json.dump(m, fh)

    def test_test_lines_do_not_count_against_the_norm(self):
        self.meta("sz__new", median_merged_pr_lines=62, median_merged_pr_nontest_lines=45)
        files = [self.changed("src/ArraySchema.ts", 64), self.changed("test/ArraySchema.test.ts", 234)]
        it = R.size("sz__new", files)
        self.assertEqual(it["status"], "pass")  # old code: 298 > 3 x 62, fail
        self.assertEqual(it["evidence"], "64 changed lines outside tests vs median merged PR 45 (234 more in tests)")

    def test_source_heavy_change_still_fails(self):
        self.meta("sz__src", median_merged_pr_lines=62, median_merged_pr_nontest_lines=40)
        self.assertEqual(R.size("sz__src", [self.changed("src/a.ts", 121)])["status"], "fail")
        self.assertEqual(R.size("sz__src", [self.changed("src/a.ts", 61)])["status"], "warn")
        self.assertEqual(R.size("sz__src", [self.changed("src/a.ts", 60), self.changed("tests/t.py", 500)])["status"],
                         "pass")
        self.assertEqual(R.size("sz__src", [self.changed("src/a.ts", 60)])["evidence"],
                         "60 changed lines outside tests vs median merged PR 40")

    def test_old_meta_keeps_the_total_and_says_how_to_fix_it(self):
        self.meta("sz__old", median_merged_pr_lines=62, learn_version=3)
        it = R.size("sz__old", [self.changed("src/a.ts", 64), self.changed("test/a.test.ts", 234)])
        self.assertEqual(it["status"], "fail")
        self.assertEqual(it["evidence"], "298 changed lines vs median merged PR 62 (234 of them in tests; re-run "
                                         "`crucible learn` to judge the lines outside tests)")
        self.assertEqual(R.size("sz__old", [self.changed("src/a.ts", 64)])["evidence"],
                         "64 changed lines vs median merged PR 62")
        self.assertIn("outside test files", R.learned_data("sz__old")["evidence"])  # and readiness says it's stale

    def test_nontest_lines_from_the_pr_file_list(self):
        from crucible import learn as L
        listed = {"repos/o/r/pulls/1/files?per_page=100": [
            {"filename": "src/a.py", "changes": 10}, {"filename": "tests/test_a.py", "changes": 30},
            {"filename": "src/a.test.js", "changes": 5}],
            "repos/o/r/pulls/2/files?per_page=100": {"message": "Not Found"}}
        orig = L.gh_json
        L.gh_json = lambda path, check=False: listed.get(path)
        try:
            self.assertEqual(L.nontest_lines("o/r", 1, 45), 10)
            self.assertEqual(L.nontest_lines("o/r", 1, 145), 110)  # files past the first 100 count as non-test
            self.assertIsNone(L.nontest_lines("o/r", 2, 45))
            self.assertIsNone(L.nontest_lines("o/r", 3, 45))
        finally:
            L.gh_json = orig

    def test_size_norms(self):
        from crucible import learn as L
        self.assertEqual(L.size_norms([(10, 4), (20, 6), (30, None), (40, 8)]),
                         {"median_merged_pr_lines": 25, "p75_merged_pr_lines": 37, "median_merged_pr_nontest_lines": 6})
        # fewer than half the PRs listed their files: no non-test median, readiness falls back to the total
        self.assertIsNone(L.size_norms([(10, 4), (20, None), (30, None)])["median_merged_pr_nontest_lines"])
        self.assertEqual(L.size_norms([]), {"median_merged_pr_lines": None, "p75_merged_pr_lines": None,
                                            "median_merged_pr_nontest_lines": None})


class TestLearnStyleSources(unittest.TestCase):
    """Bug j: `learn` measured Dependabot PR bodies and quoted the contributor's own unpushed commit as house style."""
    def setUp(self):
        self.up = make_repo({"src/core.js": "// upstream comment\nconst a = 1;\n"})
        work = tempfile.mkdtemp(prefix="crucible-clone-")
        sh(work, "git", "clone", "-q", self.up, "c")
        self.c = os.path.join(work, "c")
        sh(self.c, "git", "config", "user.email", "t@t"); sh(self.c, "git", "config", "user.name", "t")
        sh(self.c, "git", "checkout", "-qb", "fix")
        open(os.path.join(self.c, "src", "core.js"), "w").write("// LOCAL UNPUSHED narration\nconst a = 2;\n")
        open(os.path.join(self.c, "src", "local_only.js"), "w").write("// LOCAL ONLY FILE\n")
        sh(self.c, "git", "add", "-A"); sh(self.c, "git", "commit", "-qm", "local work")
        self.prompts = []

        def pr(num, login, body, typ="User"):
            return {"number": num, "title": f"Fix thing {num}", "body": body, "merged_at": "2026-11-01T00:00:00Z",
                    "html_url": f"https://github.com/o/r/pull/{num}", "author_association": "CONTRIBUTOR",
                    "user": {"login": login, "type": typ}}
        self.pulls = [pr(1, "dependabot[bot]", "Bumps lodash. " + "release notes " * 400, "Bot"),
                      pr(2, "renovate", "Update dependency x. " + "changelog " * 400),
                      pr(3, "alice", "Fixes #5.\n\nShort human body."), pr(4, "bob", "Fixes #6.\n\nAnother short one.")]

        def fake_gh(path, check=False):
            return self.pulls if path.startswith("repos/o/r/pulls?") else []

        def fake_claude(prompt, *a, **k):
            self.prompts.append(prompt)
            return {"tone": "t", "comment_conventions": "c", "callouts": "x", "avoid": "y"}, 0.0
        self._orig = (S.gh_json, S.claude)
        S.gh_json, S.claude = fake_gh, fake_claude

    def tearDown(self):
        S.gh_json, S.claude = self._orig

    def test_bots_excluded_and_code_from_upstream_branch(self):
        m = S.learn_style(self.c, "o/r", "o__r_bugj", log=lambda *_: None)
        self.assertEqual(m["prs_sampled"], 2)
        self.assertLess(m["body"]["median_words"], 10)
        self.assertNotIn("Bumps lodash", " ".join(e["body"] for e in m["examples"]))
        self.assertEqual(m["code_ref"], "origin/main")
        self.assertIn("upstream comment", self.prompts[0])
        self.assertNotIn("LOCAL", self.prompts[0])
        self.assertEqual(m["comment_density_median"], 50.0)
        self.assertEqual(m["learn_version"], U.LEARN_VERSION)  # a fresh learn is never reported as stale
        self.assertEqual(R.learned_data("o__r_bugj")["status"], "pass")

    def test_length_baseline_from_outside_contributors(self):
        """three-mesh-bvh 2026-11-06: the repeat-author sample is the owner's own one-line PRs (median 17), so a
        183-word contributor body was a medium "length reads as generated"; outside contributors' median is 144.5."""
        def pr(num, login, assoc, n_words, typ="User"):
            return {"number": num, "title": f"T{num}", "body": "word " * n_words, "merged_at": "2026-11-01T00:00:00Z",
                    "html_url": f"https://github.com/o/r/pull/{num}", "author_association": assoc,
                    "user": {"login": login, "type": typ}}
        owner = [pr(i, "owner", "OWNER", 12) for i in range(1, 16)]
        outside = [pr(20 + i, f"c{i}", ("CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "NONE")[i % 3], 140 + i) for i in range(6)]
        self.pulls = owner + outside + [pr(40, "dependabot[bot]", "CONTRIBUTOR", 900, "Bot"),
                                        pr(41, "x", "NONE", 900) | {"merged_at": None}]  # bot and unmerged: ignored
        m = S.learn_style(self.c, "o/r", "o__r_outside", log=lambda *_: None)
        self.assertEqual(m["body"]["median_words"], 12)  # the regulars' sample is unchanged
        self.assertEqual((m["body"]["outside_median_words"], m["body"]["outside_prs"]), (142, 6))
        self.assertIn("from outside contributors (6 merged PRs): median 142 words",
                      open(os.path.join(S.project_dir("o__r_outside"), "STYLE.md")).read())
        self.assertEqual(S.ai_tells("word " * 183, m), [])
        tells = dict(S.ai_tells("word " * 400, m))  # falsifier: well past the outside norm still reads as long
        self.assertEqual(tells.get("length"), "400 words vs median 142 of 6 merged PRs from outside contributors")
        # fewer than 5 outside PRs: no outside baseline, the regulars' median is used as before
        self.pulls = owner + outside[:4]
        m = S.learn_style(self.c, "o/r", "o__r_outside", log=lambda *_: None)
        self.assertNotIn("outside_median_words", m["body"])
        self.assertEqual(dict(S.ai_tells("word " * 183, m)).get("length"), "183 words vs project median 12")

    def _metered(self, cost, fail=False):
        """A stand-in for util.claude: the budget is charged before the result is checked, as in the real call."""
        def fake(prompt, model, schema, cwd, budget=None, **k):
            budget.add(cost)
            if fail:
                raise U.Failed("model call failed (error_max_turns)")
            if "rules" in schema.get("properties", {}):
                return {"rules": [{"rule": "r", "why": "w", "sources": ["s"]}]}, cost
            return {"tone": "t", "comment_conventions": "c", "callouts": "x", "avoid": "y"}, cost
        return fake

    def test_style_call_cost_is_recorded(self):
        """11-07 exchange miss: the style call's cost was discarded, so 9 style calls went unmetered."""
        S.claude = self._metered(0.37)
        m = S.learn_style(self.c, "o/r", "o__r_cost", log=lambda *_: None)
        self.assertEqual(m["cost_usd"], 0.37)
        self.assertEqual(U.read_json(os.path.join(S.project_dir("o__r_cost"), "style.json"))["cost_usd"], 0.37)

    def test_failed_style_call_is_still_metered(self):
        S.claude = self._metered(0.12, fail=True)
        m = S.learn_style(self.c, "o/r", "o__r_cost_fail", log=lambda *_: None)
        self.assertIn("convention extraction failed", m["conventions"]["tone"])
        self.assertEqual(m["cost_usd"], 0.12)

    def test_run_learn_reports_rules_plus_style_spend(self):
        from crucible import learn as L
        S.claude = self._metered(0.37)
        orig = (L.collect, L.docs_text, L.claude, L.upstream_slug)
        L.collect = lambda slug, n, log: ([{"number": 1}], [{"pr": 1, "url": "u", "path": "", "body": "b"}], [(10, 4), (20, 9)])
        L.docs_text, L.claude, L.upstream_slug = (lambda slug: ""), self._metered(0.41), (lambda repo: "o/r")
        logs = []
        try:
            meta = L.run_learn(self.c, log=logs.append)
        finally:
            L.collect, L.docs_text, L.claude, L.upstream_slug = orig
        self.assertEqual(meta["total_cost_usd"], 0.78)
        self.assertIn("learn cost $0.78 (rules $0.41, style $0.37)", logs)
        d = S.project_dir(U.project_key(self.c))
        self.assertEqual(U.read_json(os.path.join(d, "meta.json"))["cost_usd"], 0.41)
        self.assertNotIn("total_cost_usd", U.read_json(os.path.join(d, "meta.json")))
        self.assertEqual(U.read_json(os.path.join(d, "style.json"))["cost_usd"], 0.37)

    def test_rules_md_names_the_nontest_median_only_when_known(self):
        from crucible import learn as L
        S.claude = self._metered(0.0)
        d = S.project_dir(U.project_key(self.c))
        orig = (L.collect, L.docs_text, L.claude, L.upstream_slug)
        L.docs_text, L.claude, L.upstream_slug = (lambda slug: ""), self._metered(0.0), (lambda repo: "o/r")
        try:
            for sizes, want in (([(10, 4), (20, 6)], "Median merged PR: 15 changed lines (5 outside tests)."),
                                ([(10, None), (20, None)], "Median merged PR: 15 changed lines.")):
                L.collect = lambda slug, n, log, s=sizes: ([{"number": 1}], [{"pr": 1, "url": "u", "path": "", "body": "b"}], s)
                L.run_learn(self.c, log=lambda *_: None)
                self.assertIn(want, open(os.path.join(d, "rules.md")).read())
        finally:
            L.collect, L.docs_text, L.claude, L.upstream_slug = orig

    def test_run_learn_spend_without_comments_or_a_rules_call(self):
        from crucible import learn as L
        S.claude = self._metered(0.37)
        orig = (L.collect, L.docs_text, L.upstream_slug)
        L.collect, L.docs_text, L.upstream_slug = (lambda slug, n, log: ([], [], [(10, 4)])), (lambda slug: ""), (lambda r: "o/r")
        logs = []
        try:
            meta = L.run_learn(self.c, log=logs.append)
            self.assertEqual(meta["total_cost_usd"], 0.37)
            self.assertIn("learn cost $0.37 (rules $0, style $0.37)", logs)
            self.assertNotIn("cost_usd", U.read_json(os.path.join(S.project_dir(U.project_key(self.c)), "meta.json")))
            self.assertEqual(L.run_learn(self.c, style=False, log=logs.append)["total_cost_usd"], 0)
        finally:
            L.collect, L.docs_text, L.upstream_slug = orig

    def test_failed_rules_call_reports_its_spend(self):
        from crucible import learn as L
        orig = (L.collect, L.docs_text, L.claude, L.upstream_slug)
        L.collect = lambda slug, n, log: ([{"number": 1}], [{"pr": 1, "url": "u", "path": "", "body": "b"}], [(10, 4)])
        L.docs_text, L.claude, L.upstream_slug = (lambda slug: ""), self._metered(0.41, fail=True), (lambda r: "o/r")
        try:
            with self.assertRaisesRegex(U.Failed, r"error_max_turns.*learn cost \$0\.41 spent on the rules call"):
                L.run_learn(self.c, log=lambda *_: None)
            L.claude = self._metered(0, fail=True)        # a timeout: no cost figure, so no "$0 spent" claim
            with self.assertRaises(U.Failed) as cm:
                L.run_learn(self.c, log=lambda *_: None)
            self.assertNotIn("learn cost", str(cm.exception))
        finally:
            L.collect, L.docs_text, L.claude, L.upstream_slug = orig

    def test_falls_back_to_head_without_a_base_branch(self):
        d = make_repo({"x.py": "# hi\nx = 1\n"})
        sh(d, "git", "branch", "-m", "main", "topic")
        ref, files, read = S.upstream_files(d)
        self.assertEqual((ref, files), ("HEAD", ["x.py"]))
        self.assertIn("# hi", read("x.py"))

    def test_collect_skips_bot_prs_and_bot_comments(self):
        from crucible import learn as L
        comments = [{"author_association": "MEMBER", "body": "Please add a test.", "user": {"login": "carol"}},
                    {"author_association": "MEMBER", "body": "Coverage report", "user": {"login": "codecov[bot]", "type": "Bot"}}]

        def fake_gh(path, check=False):
            if path.startswith("repos/o/r/pulls?"):
                return self.pulls
            if "/comments" in path and "issues/3/" in path:
                return comments
            return {"additions": 1, "deletions": 1} if re.match(r"repos/o/r/pulls/\d+$", path) else []
        orig = L.gh_json
        L.gh_json = fake_gh
        try:
            merged, got, sizes = L.collect("o/r", log=lambda *_: None)
        finally:
            L.gh_json = orig
        self.assertEqual([p["number"] for p in merged], [3, 4])
        self.assertEqual([c["body"] for c in got], ["Please add a test."])
        self.assertEqual(sizes, [(2, 2), (2, 2)])

    def test_non_utf8_source_does_not_crash(self):
        d = make_repo({"a.js": "x\n"})
        open(os.path.join(d, "a.js"), "wb").write(b"// caf\xe9\nconst x = 1;\n")
        sh(d, "git", "commit", "-qam", "latin-1")
        ref, _files, read = S.upstream_files(d)
        self.assertEqual(ref, "main")
        self.assertTrue(read("a.js").startswith("// caf\ufffd"))
        self.assertEqual(read("missing.js"), "")

    def test_non_ascii_path_is_listed_and_read(self):
        d = make_repo({"src/café.js": "// accent\nconst x = 1;\n"})
        sh(d, "git", "config", "core.quotepath", "true")   # git's default; a global false would hide the bug
        _ref, files, read = S.upstream_files(d)
        self.assertEqual(files, ["src/café.js"])
        self.assertIn("// accent", read("src/café.js"))

    def test_is_bot(self):
        self.assertTrue(U.is_bot({"login": "dependabot[bot]", "type": "Bot"}))
        self.assertTrue(U.is_bot({"login": "Renovate", "type": "User"}))
        self.assertTrue(U.is_bot("github-actions[bot]"))
        self.assertFalse(U.is_bot({"login": "alice", "type": "User"}))
        self.assertFalse(U.is_bot(None))


class TestPackaging(unittest.TestCase):
    """`pipx install git+…` must give a working `crucible`: the entry point resolves and the files it reads ship."""
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_guide_ships_inside_the_package(self):
        from crucible import assist
        self.assertTrue(os.path.isfile(assist.DOCS), assist.DOCS)
        self.assertEqual(os.path.dirname(os.path.dirname(assist.DOCS)), os.path.join(self.ROOT, "crucible"))

    def test_entry_point_and_package_data(self):
        import fnmatch, importlib
        try:
            import tomllib
        except ImportError:   # Python 3.10; CI's install step still covers the build there
            self.skipTest("tomllib needs Python 3.11+")
        cfg = tomllib.load(open(os.path.join(self.ROOT, "pyproject.toml"), "rb"))
        mod, fn = cfg["project"]["scripts"]["crucible"].split(":")
        self.assertTrue(callable(getattr(importlib.import_module(mod), fn)))
        self.assertEqual(cfg["project"]["dependencies"], [])
        from crucible import assist
        rel = os.path.relpath(assist.DOCS, os.path.join(self.ROOT, "crucible"))
        self.assertTrue(any(fnmatch.fnmatch(rel, g) for g in cfg["tool"]["setuptools"]["package-data"]["crucible"]), rel)

    def test_eval_outside_a_clone_says_why(self):
        from crucible import evalrun
        orig = evalrun.EVAL_DIR
        evalrun.EVAL_DIR = tempfile.mkdtemp(prefix="crucible-noeval-")
        try:
            with self.assertRaises(SystemExit) as cm:
                evalrun.run_eval(type("A", (), {"cases": None})())
            self.assertIn("git clone", str(cm.exception))
        finally:
            evalrun.EVAL_DIR = orig


class TestWaivers(unittest.TestCase):
    def test_waiver_unblocks_only_the_waived_failure(self):
        from crucible.review import ready_after_waivers
        ready = {"items": [{"item": "tests updated for behaviour change", "status": "fail"},
                           {"item": "issue linked", "status": "pass"}]}
        self.assertFalse(ready_after_waivers(ready, {}))
        self.assertTrue(ready_after_waivers(ready, {"tests updated for behaviour change": "no WebGPU backend test suite"}))
        ready["items"].append({"item": "no formatting-only churn", "status": "fail"})
        self.assertFalse(ready_after_waivers(ready, {"tests updated for behaviour change": "x"}))


class TestClaudeCall(unittest.TestCase):
    def test_prompt_is_sent_on_stdin_not_argv(self):
        # --allowedTools is variadic, so a trailing positional prompt was parsed as a tool name
        import json
        from unittest import mock
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"], seen["input"] = cmd, kw.get("input")
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"structured_output": {"ok": True}}), "")

        with mock.patch.object(U.subprocess, "run", fake_run):
            out, _ = U.claude("PROMPT-TEXT", "m", {"type": "object"}, ".")
        self.assertEqual(out, {"ok": True})
        self.assertEqual(seen["input"], "PROMPT-TEXT")
        self.assertNotIn("PROMPT-TEXT", seen["cmd"])


    def test_verifier_can_run_python_tests_and_probes_without_bytecode(self):
        # 58 of 149 stored Python verifications had `python3 -m unittest` or `python3 -c` refused and fell back to
        # reading; the verifier gets the same reach on Python as `node:*` gives it on JS
        import json
        from unittest import mock
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"], seen["env"] = cmd, kw.get("env")
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"structured_output": {"ok": True}}), "")

        with mock.patch.object(U.subprocess, "run", fake_run):
            U.claude("p", "m", {"type": "object"}, ".", tools=U.TOOLS_RUN)
        allowed = seen["cmd"][seen["cmd"].index("--allowedTools") + 1].split(",")
        for rule in ("Bash(python3 -m unittest:*)", "Bash(python3 -c:*)", "Bash(python -m unittest:*)",
                     "Bash(python3 -m pytest:*)", "Bash(node:*)"):
            self.assertIn(rule, allowed)
        self.assertFalse(any(r.startswith(("Bash(python3:", "Bash(rm", "Bash(git commit", "Bash(git push"))
                             for r in allowed), allowed)   # runners only, never a bare interpreter or a write verb
        self.assertEqual(seen["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertNotIn("python3 -c", ",".join(U.TOOLS_READ))   # reviewers and tool-less calls stay read-only
        self.assertIn("python3 -m unittest", V.verify_prompt(
            {"title": "t", "file": "a.py", "line": 1, "severity": "low", "wrong_if": "w"}, "code"))

    def test_prose_answer_without_structured_output_is_typed(self):
        # bug l: the CLI reports subtype "success" with the verdict in `result` when every StructuredOutput call
        # was rejected; callers need that text, not just a generic failure
        import json
        from unittest import mock
        payload = {"subtype": "success", "is_error": False, "result": "Verdict: the claim does not hold."}

        def fake_run(cmd, **kw):
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

        with mock.patch.object(U.subprocess, "run", fake_run):
            with self.assertRaises(U.NoStructuredOutput) as cm:
                U.claude("p", "m", {"type": "object"}, ".")
        self.assertEqual(cm.exception.text, "Verdict: the claim does not hold.")
        for bad in ({"subtype": "error_max_turns", "is_error": True, "result": "x"}, {"subtype": "success", "result": ""}):
            payload = bad
            with mock.patch.object(U.subprocess, "run", fake_run):
                with self.assertRaises(U.Failed) as cm:
                    U.claude("p", "m", {"type": "object"}, ".")
            self.assertNotIsInstance(cm.exception, U.NoStructuredOutput)


class TestVerifierSalvage(unittest.TestCase):
    """Bug l: the verifier's StructuredOutput call was rejected ("must have required property 'confidence'") and the
    finding came back unverified although the prose held a clear verdict (5 of 415 verifications, 2026-11-04)."""
    F = {"title": "off by one", "file": "a.js", "line": 3, "severity": "medium", "wrong_if": "x"}

    def run_tiered(self, fake, tiers, cache=None):
        from unittest import mock
        env = {"CRUCIBLE_CACHE": cache, "CRUCIBLE_CACHE_VERIFY": "1"} if cache else {"CRUCIBLE_CACHE_VERIFY": "0"}
        with mock.patch.object(V, "claude", fake), mock.patch.dict(os.environ, env):
            return V.verify_tiered(self.F, "code", ".", None, tiers)

    def test_prose_verdict_is_transcribed_not_left_unverified(self):
        calls = []

        def fake(prompt, model, schema, cwd, budget=None, tools=None, **kw):
            calls.append((model, tools))
            if model == "strong":
                raise U.NoStructuredOutput("model call failed (success): ...", "**Verdict: claim falsified.** I ran it.")
            self.assertIn("claim falsified", prompt)
            return {"keep": False, "severity": "medium", "confidence": "high", "method": "executed",
                    "actions": "ran it", "evidence": "falsified"}, 0.001
        v, trail = self.run_tiered(fake, ["strong"])
        self.assertFalse(v["keep"])
        self.assertEqual(calls, [("strong", V.TOOLS_RUN), (V.SALVAGE_MODEL, None)])   # transcription runs no tools
        self.assertTrue(trail[0]["salvaged"])
        self.assertEqual(v["confidence"], "medium")       # second-hand: never high

    def test_salvaged_cheap_verdict_escalates_and_is_not_cached(self):
        calls = []

        def fake(prompt, model, schema, cwd, budget=None, tools=None, **kw):
            calls.append(model)
            if model == "cheap":
                raise U.NoStructuredOutput("x", "Verdict: claim falsified.")
            return {"keep": False, "severity": "low", "confidence": "high", "method": "read",
                    "actions": "a", "evidence": "e"}, 0
        with tempfile.TemporaryDirectory() as d:
            self.run_tiered(fake, ["cheap", "strong"], cache=d)
            self.assertEqual(calls, ["cheap", V.SALVAGE_MODEL, "strong"])   # a transcription is never final
            calls.clear()
            self.run_tiered(fake, ["cheap", "strong"], cache=d)
            self.assertEqual(calls[0], "cheap")                              # not replayed from the cache
            self.assertTrue(os.listdir(d))                                   # the first-hand verdict was cached

    def test_a_failed_transcription_fails_closed(self):
        def fake(prompt, model, *a, **kw):
            if model == "strong":
                raise U.NoStructuredOutput("x", "Verdict: holds.")
            raise U.Failed("model call timed out after 300s")
        with self.assertRaises(U.Failed):            # run_review keeps the finding as "unverified"
            self.run_tiered(fake, ["strong"])

    def test_other_failures_still_fail_closed(self):
        def fake(*a, **kw):
            raise U.Failed("model call timed out after 1500s")
        with self.assertRaises(U.Failed):
            self.run_tiered(fake, ["strong"])

    def test_report_marks_transcribed_verdicts(self):
        tiers = [{"model": "cheap", "salvaged": True}, {"model": "strong"}]
        self.assertEqual(V.transcribed_note({"tiers": tiers}), "")          # the strong tier decided it first-hand
        self.assertIn("transcribed", V.transcribed_note({"tiers": tiers[:1]}))
        self.assertEqual(V.transcribed_note({"status": "unverified", "reason": "x"}), "")
        f = dict(self.F, id="CR-1", problem="p", fix="x", verification={
            "status": "dropped", "method": "read", "actions": "a", "evidence": "falsified", "tiers": tiers[:1]})
        rev = {"repo": "o__r", "sha": "a" * 40, "status": "done", "readiness": {"items": []}, "findings": [],
               "dropped": [f], "coverage": {"reviewed": 1, "files": 1, "missing": [], "complete": True}, "review_model": "r",
               "verify_model": "v", "base_ref": "main", "base": "b" * 40, "cost_usd": 0, "checks": {}}
        self.assertIn("(`a.js:3`) (transcribed from the verifier's prose): falsified", V.report(rev, {}))

    def test_short_fields_come_before_free_text(self):
        keys = list(V.VERIFY_SCHEMA["properties"])
        self.assertLess(keys.index("confidence"), keys.index("evidence"))
        self.assertEqual(keys[-1], "evidence")
        self.assertEqual(set(V.VERIFY_SCHEMA["required"]), set(keys))


class TestRealUseBugs(unittest.TestCase):
    """Regression tests for bugs found while reviewing real upstream PRs (real-use bugs a–e)."""

    def test_a_bare_pr_number_is_not_an_issue_link(self):
        self.assertIsNone(R.linked_issue("This overlaps #2693 and #2694."))
        self.assertEqual(R.linked_issue("Closes #2823\n\nOverlaps #2693."), 2823)
        self.assertEqual(R.linked_issue("Related issue: #34697"), 34697)
        self.assertEqual(R.linked_issue("see https://github.com/o/r/issues/77"), 77)
        self.assertIsNone(R.linked_issue("Closes #(issue_number)"))

    def test_a_placeholder_is_reported(self):
        for t in ("Closes #(issue_number)", "Fixes #ISSUE", "Related issue: #XXXX", "closes #<n>"):
            self.assertIsNotNone(R.issue_placeholder(t), t)
        self.assertIsNone(R.issue_placeholder("Closes #12"))

    def test_b_monorepo_checks_use_the_touched_package(self):
        from crucible import checks as C
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "package.json"), "w").write('{"name":"root","scripts":{"test":"nx run-many -t test"}}')
            open(os.path.join(d, "nx.json"), "w").write("{}")
            pk = os.path.join(d, "packages", "core", "postgrest-js")
            os.makedirs(os.path.join(pk, "src"))
            open(os.path.join(pk, "package.json"), "w").write('{"name":"pg","scripts":{"test":"jest","lint":"eslint ."}}')
            det = C.detect(d, "x", ["packages/core/postgrest-js/src/PostgrestClient.ts"])
            self.assertEqual({c["cwd"] for c in det["checks"]}, {"packages/core/postgrest-js"})
            self.assertEqual(sorted(c["name"].split()[-1] for c in det["checks"]), ["lint", "test"])
            self.assertEqual(C.detect(d, "x", ["README.md"])["checks"][0].get("cwd"), None)  # falls back to the root

    def test_c_polish_keeps_issue_link_lines(self):
        body, restored = S.keep_required_lines("Closes #12\n\nFixes the thing.", "Fixes the thing, cleanly.")
        self.assertEqual(restored, ["Closes #12"])
        self.assertTrue(body.startswith("Closes #12\n\n"))
        body, restored = S.keep_required_lines("Text.\n\nRelated issue: #5", "Text, better.")
        self.assertTrue(body.endswith("Related issue: #5"))
        self.assertEqual(S.keep_required_lines("Closes #1\nx", "Closes #1\ny")[1], [])

    def test_d_polished_draft_is_not_judged_implicitly(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "PR_DRAFT.polished.md"), "w").write("# P\n\npolished")
            self.assertEqual(R.find_draft(d), (None, ""))
            open(os.path.join(d, "PR_DRAFT.md"), "w").write("# T\n\nmine")
            self.assertTrue(R.find_draft(d)[0].endswith("PR_DRAFT.md"))
            self.assertTrue(R.find_draft(d, os.path.join(d, "PR_DRAFT.polished.md"))[0].endswith("polished.md"))

    def test_e_cache_key_ignores_volatile_check_output(self):
        a = {"results": [{"cmd": "npm test", "status": "pass", "tail": "done in 1.2s"}]}
        b = {"results": [{"cmd": "npm test", "status": "pass", "tail": "done in 3.9s"}]}
        self.assertEqual(V.facts_key(a), V.facts_key(b))
        self.assertNotEqual(V.facts_key(a), V.facts_key({"results": [{"cmd": "npm test", "status": "fail"}]}))


class TestTiers(unittest.TestCase):
    def test_tier_selection(self):
        os.environ.pop("CRUCIBLE_VERIFY_CHEAP", None)
        self.assertEqual(V.verify_tiers("claude-sonnet-5-5"), ["claude-haiku-5-5", "claude-sonnet-5-5"])
        self.assertEqual(V.verify_tiers("claude-sonnet-5-5", no_tiers=True), ["claude-sonnet-5-5"])
        os.environ["CRUCIBLE_VERIFY_CHEAP"] = "none"
        try:
            self.assertEqual(V.verify_tiers("claude-sonnet-5-5"), ["claude-sonnet-5-5"])
        finally:
            os.environ.pop("CRUCIBLE_VERIFY_CHEAP")

    def test_escalation_rules(self):
        self.assertTrue(V.needs_escalation({"keep": True, "severity": "important", "confidence": "high"}))
        self.assertTrue(V.needs_escalation({"keep": False, "severity": "low", "confidence": "medium"}))
        self.assertFalse(V.needs_escalation({"keep": False, "severity": "important", "confidence": "high"}))
        self.assertFalse(V.needs_escalation({"keep": True, "severity": "low", "confidence": "high"}))


class TestIncremental(unittest.TestCase):
    def test_split_prev_carries_untouched_and_reverifies_touched(self):
        prev = [{"source": "review", "file": "a.js", "line": 6, "title": "off by one"},
                {"source": "review", "file": "b.js", "line": 5, "title": "lastN(0)"},
                {"source": "review", "file": "a.js", "line": 40, "title": "far below"},
                {"source": "style", "file": "PR_DRAFT.md", "line": 1, "title": "length"}]
        # a.js: lines 6..6 replaced, and 2 lines added at 20 → line 40 moves to 42
        diff = ("diff --git a/a.js b/a.js\n--- a/a.js\n+++ b/a.js\n@@ -6 +6 @@\n-x\n+y\n@@ -20,0 +21,2 @@\n+p\n+q\n")
        ranges, hunks = D.changed_old_ranges(diff), D.hunks_old_new(diff)
        carried, touched = V.split_prev(prev, ranges, hunks, "f" * 40)
        self.assertEqual([f["title"] for f in touched], ["off by one"])
        self.assertEqual({f["title"]: f["line"] for f in carried}, {"lastN(0)": 5, "far below": 42})
        self.assertTrue(all(f["carried_from"] == "f" * 10 for f in carried))

    def test_absence_finding_reverified_when_its_anchor_changes(self):
        # ROADMAP item 1 (BLAZE exchange 2026-11-05): "no test for X" cites X, but the fix lands in a test file, so
        # its own lines never change. It is re-verified when its anchor changed, and carried otherwise.
        prev = [{"source": "review", "file": "r.py", "line": 9, "title": "Guard is subtle", "anchor_files": ["t.py"]},
                {"source": "review", "file": "r.py", "line": 9, "title": "Docs gap", "anchor_files": ["README.md"]},
                {"source": "review", "file": "r.py", "line": 9, "title": "No test for the new recheck guard"},
                {"source": "review", "file": "r.py", "line": 9, "title": "Off-by-one in the guard"}]
        carried, touched = V.split_prev(prev, {}, {}, "f" * 40, changed=["t.py"], known=["t.py", "README.md", "r.py"])
        self.assertEqual({f["title"]: f["anchor_changed"] for f in touched},
                         {"Guard is subtle": ["t.py"], "No test for the new recheck guard": ["t.py"]})
        self.assertEqual(sorted(f["title"] for f in carried), ["Docs gap", "Off-by-one in the guard"])
        # nothing changed since: every finding carries, absence or not
        carried, touched = V.split_prev(prev, {}, {}, "f" * 40, changed=[])
        self.assertEqual((len(carried), touched), (4, []))
        # an earlier round's anchor_changed doesn't ride along into this round's re-verify
        old = [dict(prev[3], anchor_changed=["t.py"], line=9)]
        ranges = D.changed_old_ranges("diff --git a/r.py b/r.py\n--- a/r.py\n+++ b/r.py\n@@ -9 +9 @@\n-x\n+y\n")
        _, touched = V.split_prev(old, ranges, {}, "f" * 40, changed=["r.py"])
        self.assertNotIn("anchor_changed", touched[0])

    def test_anchor_hits_tolerate_a_wrong_guess(self):
        known = {"tests/test_core.py", "crucible/review.py", "crucible/util.py", "CHANGELOG.md"}
        # a real anchor must change itself; an edit next to it (crucible/util.py) costs no re-verify
        self.assertEqual(V.anchor_hits(["tests/test_core.py"], {"tests/test_core.py", "README.md"}, known),
                         ["tests/test_core.py"])
        self.assertEqual(V.anchor_hits(["crucible/review.py"], {"crucible/util.py"}, known), [])
        self.assertEqual(V.anchor_hits(["CHANGELOG.md"], {"tests/x/t.py"}, known), [])
        # an imagined test file: any change in its directory counts, also next to a real anchor (CR-398406d7)
        self.assertEqual(V.anchor_hits(["tests/test_review.py"], {"tests/test_core.py", "README.md"}, known),
                         ["tests/test_core.py"])
        self.assertEqual(V.anchor_hits(["tests/test_review.py", "CHANGELOG.md"], {"tests/test_core.py"}, known),
                         ["tests/test_core.py"])
        # an imagined file at the root or in a directory that doesn't exist: any change counts
        self.assertEqual(V.anchor_hits(["test_review.py"], {"crucible/util.py"}, known), ["crucible/util.py"])
        self.assertEqual(V.anchor_hits(["spec/review.spec.js"], {"crucible/util.py"}, known), ["crucible/util.py"])
        self.assertEqual(V.absence_anchor({"title": "x", "anchor_files": ["./tests/test_core.py"]}), ["tests/test_core.py"])

    def test_absence_rx_falsifiers(self):
        # real titles from ~/.crucible/reviews (2026-11-04/05): these say something is missing ...
        for t in ["No test for the new recheck guard on transcribed verdicts", "No CHANGELOG entry for a user-visible "
                  "behaviour change", "Report line, cache behaviour and failure of the salvage call are untested",
                  "Skinned-tangent exclusion from the copy path isn't covered", "Tests don't cover the ordering the fix "
                  "depends on", "The perf test never exercises untracked paths", "New scoring rule only partly tested",
                  "Missing comment on why the normalisation replaces with a space"]:
            self.assertIsNotNone(V.absence_anchor({"title": t}), t)
        # ... and these are about code that is there, so their cited lines decide
        for t in ["New trailing \\b in TESTED_RX stops matching plurals", "README overstates the guarantee of the clean "
                  "re-run", "Garbled changelog sentence from a bad merge of two clauses", "Wall-clock assertion in a "
                  "unit test", "New test only fails without the fix under git's default quotepath",
                  "Docstring says both diffs have 3 context lines, but ours is parsed with --unified=5"]:
            self.assertIsNone(V.absence_anchor({"title": t}), t)
        self.assertEqual(V.absence_anchor({"title": "x", "anchor_files": ["t.py", "", 3]}), ["t.py"])

    def test_previous_review_same_base_complete_and_still_present(self):
        with tempfile.TemporaryDirectory() as d:
            home = os.path.join(d, "home"); repo = os.path.join(d, "r"); os.makedirs(repo)
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True,
                                          env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")).stdout.decode().strip()
            g("init", "-q", "-b", "main"); open(os.path.join(repo, "f"), "w").write("1"); g("add", "f"); g("commit", "-qm", "b")
            base = g("rev-parse", "HEAD"); g("checkout", "-qb", "x")
            open(os.path.join(repo, "f"), "w").write("2"); g("commit", "-qam", "c1"); c1 = g("rev-parse", "HEAD")
            open(os.path.join(repo, "f"), "w").write("3"); g("commit", "-qam", "c2"); c2 = g("rev-parse", "HEAD")
            old = (V.HOME, U.HOME)
            V.HOME = U.HOME = home
            try:
                proj = "r"
                os.makedirs(os.path.join(home, "projects", proj)); os.makedirs(os.path.join(home, "reviews", proj, c1))
                U.write_json(os.path.join(home, "projects", proj, "branches.json"), {"x": [c1]})
                rev = {"status": "done", "base": base, "coverage": {"complete": True}}
                U.write_json(os.path.join(home, "reviews", proj, c1, "review.json"), rev)
                self.assertEqual(V.previous_review(repo, proj, c2, base)[0], c1)
                self.assertEqual(V.previous_review(repo, proj, c2, "0" * 40), (None, None))       # base moved
                U.write_json(os.path.join(home, "reviews", proj, c1, "review.json"), dict(rev, coverage={"complete": False}))
                self.assertEqual(V.previous_review(repo, proj, c2, base), (None, None))          # incomplete
                U.write_json(os.path.join(home, "reviews", proj, c1, "review.json"), rev)
                # c1 amended (branch x reset to c1 first) is no ancestor of c1', but has the same merge-base: still the previous round
                g("checkout", "-qB", "x", c1); open(os.path.join(repo, "f"), "w").write("1a"); g("commit", "-q", "--amend", "-am", "c1'")
                c1a = g("rev-parse", "HEAD")
                self.assertFalse(V.is_ancestor(repo, c1, c1a))
                self.assertEqual(V.previous_review(repo, proj, c1a, base)[0], c1)
                # a commit that no longer exists (garbage-collected) can't be diffed against
                U.write_json(os.path.join(home, "projects", proj, "branches.json"), {"x": ["f" * 40, c1]})
                os.makedirs(os.path.join(home, "reviews", proj, "f" * 40))
                U.write_json(os.path.join(home, "reviews", proj, "f" * 40, "review.json"), rev)
                self.assertEqual(V.previous_review(repo, proj, c1a, base)[0], c1)
                U.write_json(os.path.join(home, "projects", proj, "branches.json"), {"x": ["f" * 40]})
                self.assertEqual(V.previous_review(repo, proj, c1a, base), (None, None))
                # the branch name reused for an unrelated change (no changed file in common): start over
                U.write_json(os.path.join(home, "projects", proj, "branches.json"), {"x": [c1]})
                g("checkout", "-qB", "x", base); open(os.path.join(repo, "other"), "w").write("o"); g("add", "other")
                g("commit", "-qm", "unrelated"); u = g("rev-parse", "HEAD")
                self.assertEqual(V.previous_review(repo, proj, u, base), (None, None))
            finally:
                V.HOME, U.HOME = old


    def test_previous_review_detached_heads_dont_share_history(self):
        # the independent bench reviewed several PRs' heads in one checkout, detached: all recorded under "HEAD"
        with tempfile.TemporaryDirectory() as d:
            home = os.path.join(d, "home"); repo = os.path.join(d, "r"); os.makedirs(repo)
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True,
                                          env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")).stdout.decode().strip()
            g("init", "-q", "-b", "main"); open(os.path.join(repo, "f"), "w").write("1"); g("add", "f"); g("commit", "-qm", "b")
            base = g("rev-parse", "HEAD")
            open(os.path.join(repo, "f"), "w").write("pr1"); g("commit", "-qam", "pr1"); a = g("rev-parse", "HEAD")
            open(os.path.join(repo, "f"), "w").write("pr1 round 2"); g("commit", "-qam", "pr1 r2"); a2 = g("rev-parse", "HEAD")
            g("checkout", "-q", "--detach", base)
            open(os.path.join(repo, "f"), "w").write("pr2"); g("commit", "-qam", "pr2"); b = g("rev-parse", "HEAD")
            old = (V.HOME, U.HOME)
            V.HOME = U.HOME = home
            try:
                proj = "r"
                os.makedirs(os.path.join(home, "projects", proj)); os.makedirs(os.path.join(home, "reviews", proj, a))
                U.write_json(os.path.join(home, "projects", proj, "branches.json"), {"HEAD": [a]})
                U.write_json(os.path.join(home, "reviews", proj, a, "review.json"),
                             {"status": "done", "base": base, "coverage": {"complete": True}})
                # another PR's head: same base, same file changed. On a branch this would read as an amend
                self.assertEqual(g("rev-parse", "--abbrev-ref", "HEAD"), "HEAD")
                self.assertEqual(V.previous_review(repo, proj, b, base), (None, None))
                self.assertEqual(V.branch_history(repo, proj, b), [])
                # a later commit on top of the reviewed detached head is still its next round
                g("checkout", "-q", "--detach", a2)
                self.assertEqual(V.previous_review(repo, proj, a2, base)[0], a)
                # the same history on a named branch keeps the amend rule (unchanged behaviour)
                g("checkout", "-qb", "y", b)
                U.write_json(os.path.join(home, "projects", proj, "branches.json"), {"y": [a]})
                self.assertEqual(V.previous_review(repo, proj, b, base)[0], a)
            finally:
                V.HOME, U.HOME = old

    def test_carry_forward_ignores_other_detached_heads(self):
        with tempfile.TemporaryDirectory() as d:
            home = os.path.join(d, "home"); repo = os.path.join(d, "r"); os.makedirs(repo)
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True,
                                          env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")).stdout.decode().strip()
            g("init", "-q", "-b", "main"); open(os.path.join(repo, "f"), "w").write("1\n2\n3\n"); open(os.path.join(repo, "g"), "w").write("g\n")
            g("add", "f", "g"); g("commit", "-qm", "b"); base = g("rev-parse", "HEAD")
            open(os.path.join(repo, "f"), "w").write("1\nX\n3\n"); g("commit", "-qam", "pr1"); a = g("rev-parse", "HEAD")
            g("checkout", "-q", "--detach", base)
            open(os.path.join(repo, "f"), "w").write("1\nX\n3\n"); open(os.path.join(repo, "g"), "w").write("h\n")
            g("commit", "-qam", "pr2"); b = g("rev-parse", "HEAD")
            old = (V.HOME, U.HOME)
            V.HOME = U.HOME = home
            try:
                proj = "r"
                os.makedirs(os.path.join(home, "projects", proj)); os.makedirs(os.path.join(home, "reviews", proj, a))
                fnd = {"id": "f-2-x", "file": "f", "line": 2, "title": "t", "severity": "low"}
                U.write_json(os.path.join(home, "projects", proj, "branches.json"), {"HEAD": [a]})
                U.write_json(os.path.join(home, "reviews", proj, a, "review.json"), {"findings": [fnd]})
                U.write_json(os.path.join(home, "reviews", proj, a, "answers.json"), {"f-2-x": {"answer": "wontfix: pr1's reason"}})
                record = {"findings": [dict(fnd)]}
                V.carry_forward(repo, proj, b, record)
                self.assertNotIn("carried_answers", record)
                self.assertFalse(os.path.exists(os.path.join(home, "reviews", proj, b, "answers.json")))
            finally:
                V.HOME, U.HOME = old

    def test_waivers_are_per_commit_on_a_detached_head(self):
        with tempfile.TemporaryDirectory() as repo:
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True,
                                          env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")).stdout.decode().strip()
            g("init", "-q", "-b", "main"); open(os.path.join(repo, "f"), "w").write("1"); g("add", "f"); g("commit", "-qm", "b")
            self.assertEqual(V.waiver_key(repo), "main")
            base = g("rev-parse", "HEAD")
            open(os.path.join(repo, "f"), "w").write("2"); g("commit", "-qam", "pr1"); a = g("rev-parse", "HEAD")
            g("checkout", "-q", "--detach", a)
            self.assertEqual(V.waiver_key(repo), "HEAD@" + a)
            g("checkout", "-q", "--detach", base); open(os.path.join(repo, "f"), "w").write("3"); g("commit", "-qam", "pr2")
            self.assertEqual(V.waiver_key(repo), "HEAD@" + g("rev-parse", "HEAD"))
            self.assertNotEqual(V.waiver_key(repo), "HEAD@" + a)

    def test_waive_on_one_detached_head_does_not_apply_to_another(self):
        import argparse, contextlib, io
        from crucible import cli
        with tempfile.TemporaryDirectory() as d:
            home = os.path.join(d, "home"); repo = os.path.join(d, "r"); os.makedirs(repo)
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True,
                                          env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")).stdout.decode().strip()
            g("init", "-q", "-b", "main"); open(os.path.join(repo, "f"), "w").write("1"); g("add", "f"); g("commit", "-qm", "b")
            base = g("rev-parse", "HEAD")
            open(os.path.join(repo, "f"), "w").write("2"); g("commit", "-qam", "pr1"); a = g("rev-parse", "HEAD")
            g("checkout", "-q", "--detach", base); open(os.path.join(repo, "f"), "w").write("3"); g("commit", "-qam", "pr2")
            b = g("rev-parse", "HEAD")
            old = (V.HOME, U.HOME)
            V.HOME = U.HOME = home
            try:
                proj = U.project_key(repo)
                for sha in (a, b):
                    os.makedirs(os.path.join(home, "reviews", proj, sha))
                    U.write_json(os.path.join(home, "reviews", proj, sha, "review.json"),
                                 {"status": "done", "findings": [], "readiness": {"items": [{"item": "issue linked", "status": "fail"}]}})
                g("checkout", "-q", "--detach", a)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    cli.cmd_waive(argparse.Namespace(repo=repo, item="issue linked", reason="no tracker used in this project"))
                self.assertIn(f"detached commit {a[:10]}", out.getvalue())
                self.assertIn("issue linked", V.load_waivers(proj, V.waiver_key(repo)))      # what cmd_status reads
                g("checkout", "-q", "--detach", b)
                self.assertEqual(V.load_waivers(proj, V.waiver_key(repo)), {})
            finally:
                V.HOME, U.HOME = old

class TestEvalScoring(unittest.TestCase):
    def test_hits_and_scores(self):
        from crucible import evalrun as E
        exp = {"kind": "bug", "file": "src/a.js", "lines": [10], "keywords": ["off-by-one"]}
        self.assertTrue(E.hits({"file": "src/a.js", "line": 11, "title": "x", "problem": ""}, exp))
        self.assertFalse(E.hits({"file": "src/a.js", "line": 12, "title": "no tests for mean()", "problem": ""}, exp))
        self.assertTrue(E.hits({"file": "src/a.js", "line": 40, "title": "an off-by-one", "problem": ""}, exp))
        self.assertFalse(E.hits({"file": "src/b.js", "line": 10, "title": "off-by-one", "problem": ""}, exp))
        rev = {"status": "done", "cost_usd": 0.2, "dropped": [],
               "findings": [{"severity": "medium", "file": "src/a.js", "line": 10, "title": "x", "problem": ""}]}
        s = E.score_case(rev, exp)
        self.assertEqual((s["caught"], s["caught_any_severity"]), (False, True))
        s = E.score_case(dict(rev, findings=[dict(rev["findings"][0], severity="important")]), {"kind": "clean"})
        self.assertEqual(s["false_blocking"], 1)

    def test_cases_are_well_formed(self):
        from crucible import evalrun as E
        cases = E.load_cases()
        self.assertGreaterEqual(len(cases), 16)
        for name, d, exp in cases:
            self.assertIn(exp["kind"], ("bug", "clean"), name)
            self.assertTrue(os.path.isdir(os.path.join(d, "base")) and os.path.isdir(os.path.join(d, "change")), name)
            self.assertIn(E.case_split(exp), E.SPLITS, name)
            if exp["kind"] == "bug":
                self.assertTrue(exp["file"] and exp["lines"] and exp["keywords"], name)
                self.assertTrue(os.path.exists(os.path.join(d, "change", exp["file"])), name)
        held = [(n, e["kind"]) for n, d, e in E.load_cases(split="holdout")]
        self.assertIn(("py-fix-reintroduces-hang", "bug"), held)
        self.assertIn(("clean-py-bounded-shutdown", "clean"), held)
        self.assertEqual(len(E.load_cases(split="build")) + len(held), len(cases))

    def test_reintroduced_hang_case_scores_the_callee_not_a_neighbour(self):
        """gamescope #2516 round 2, as a held-out case: the credited finding must name the clear()/join that still
        waits without a bound, not just sit in pool.py."""
        from crucible import evalrun as E
        exp = {n: e for n, d, e in E.load_cases(["py-fix-reintroduces-hang"])}["py-fix-reintroduces-hang"]
        line = open(os.path.join(E.EVAL_DIR, "cases", "py-fix-reintroduces-hang", "change", exp["file"])) \
            .read().split("\n")[exp["lines"][0] - 1]
        self.assertEqual(line.strip(), "self.jobs.clear()")
        self.assertTrue(E.hits({"file": "workers/pool.py", "line": 25, "title": "shutdown can still hang",
                                "problem": "clear() closes each job with an unbounded join() before the deadline"}, exp))
        self.assertFalse(E.hits({"file": "workers/pool.py", "line": 7, "title": "magic number for the timeout",
                                 "problem": "5.0 should be configurable"}, exp))
        # a reviewer that follows the call and anchors on the join itself has found the same bug
        self.assertTrue(E.hits({"file": "workers/jobs.py", "line": 15, "title": "x", "problem": ""}, exp))
        self.assertTrue(E.hits({"file": "workers/jobs.py", "line": 40, "title": "close() joins without a timeout",
                                "problem": ""}, exp))
        self.assertFalse(E.hits({"file": "workers/jobs.py", "line": 25, "title": "pending() is O(n)", "problem": ""}, exp))
        self.assertEqual(open(os.path.join(E.EVAL_DIR, "cases", "py-fix-reintroduces-hang", "change", "workers",
                                           "jobs.py")).read().split("\n")[14].strip(), "self._thread.join()")

    def test_split_filter_and_bad_split(self):
        from crucible import evalrun as E
        orig = E.EVAL_DIR
        E.EVAL_DIR = tempfile.mkdtemp(prefix="crucible-evalsplit-")
        try:
            for name, extra in (("a", {}), ("b", {"split": "holdout"}), ("c", {"split": "build"})):
                os.makedirs(os.path.join(E.EVAL_DIR, "cases", name))
                json.dump({"kind": "clean", **extra}, open(os.path.join(E.EVAL_DIR, "cases", name, "expected.json"), "w"))
            self.assertEqual([n for n, d, e in E.load_cases(split="build")], ["a", "c"])
            self.assertEqual([n for n, d, e in E.load_cases(split="holdout")], ["b"])
            self.assertEqual(len(E.load_cases()), 3)
            for bad in ("test", "", None, "Holdout"):   # only a missing key defaults; "" or null is a typo
                json.dump({"kind": "clean", "split": bad}, open(os.path.join(E.EVAL_DIR, "cases", "c", "expected.json"), "w"))
                with self.assertRaises(SystemExit, msg=repr(bad)) as cm:
                    E.load_cases()
                self.assertIn("split must be one of build, holdout", str(cm.exception))
        finally:
            shutil.rmtree(E.EVAL_DIR, ignore_errors=True)
            E.EVAL_DIR = orig

    def test_crashed_case_stays_in_its_split(self):
        """a held-out case whose run raises must show as an error on the held-out line, not vanish into build."""
        from crucible import evalrun as E
        orig, orig_run = E.EVAL_DIR, E.run_case
        E.EVAL_DIR = tempfile.mkdtemp(prefix="crucible-evalcrash-")
        try:
            for name, exp in (("h", {"kind": "bug", "split": "holdout", "file": "a", "lines": [1], "keywords": ["x"]}),
                              ("b", {"kind": "clean"})):
                os.makedirs(os.path.join(E.EVAL_DIR, "cases", name))
                json.dump(exp, open(os.path.join(E.EVAL_DIR, "cases", name, "expected.json"), "w"))

            def fake(name, d, exp, args, cache):
                if name == "h":
                    raise subprocess.TimeoutExpired("review", 3600)
                return {"case": name, "kind": "clean", "split": "build", "ok": True, "false_blocking": 0, "blocking": 0,
                        "kept": 0, "dropped": 0, "cost": 0}
            E.run_case = fake
            args = type("A", (), {"cases": None, "split": None, "cache": None, "review_model": None, "verify_model": None,
                                  "cheap_model": None, "no_tiers": False, "budget": 1, "jobs": 2, "no_write": True,
                                  "label": None})()
            out = []
            s = E.run_eval(args, log=out.append)
            self.assertEqual(s["by_split"]["holdout"]["errors"], 1)
            self.assertEqual(s["by_split"]["build"]["errors"], 0)
            self.assertIn("  holdout: recall n/a (no bug cases), false blocking n/a (no clean cases), 1 errored (not scored)", out)
            # run_eval's own wiring: --cases and --split runs are partial (history only), a plain run writes RESULTS.md
            args.no_write = False
            for cases, split, subset in ((["b"], None, True), (None, "build", False)):
                args.cases, args.split = cases, split
                E.run_eval(args, log=out.append)
                self.assertFalse(os.path.exists(os.path.join(E.EVAL_DIR, "RESULTS.md")))
                row = json.loads(open(os.path.join(E.EVAL_DIR, "history.jsonl")).read().split("\n")[-2])
                self.assertEqual((row["settings"]["subset"], row["settings"]["split"]), (subset, split or "all"))
            args.cases, args.split = None, None
            E.run_eval(args, log=out.append)
            md = open(os.path.join(E.EVAL_DIR, "RESULTS.md")).read()
            self.assertIn("| 1, subset |", md)
            self.assertIn("| 1, build only |", md)
            self.assertIn("| 2 |", md)
        finally:
            shutil.rmtree(E.EVAL_DIR, ignore_errors=True)
            E.EVAL_DIR, E.run_case = orig, orig_run

    def test_holdout_recall_reported_apart_from_build(self):
        from crucible import evalrun as E
        res = [{"case": "b1", "kind": "bug", "split": "build", "ok": True, "caught": True, "caught_any_severity": True,
                "true_dropped": 0, "extra_blocking": 0},
               {"case": "b2", "kind": "bug", "split": "build", "ok": True, "caught": True, "caught_any_severity": True,
                "true_dropped": 0, "extra_blocking": 0},
               {"case": "h1", "kind": "bug", "split": "holdout", "ok": True, "caught": False,
                "caught_any_severity": True, "true_dropped": 1, "extra_blocking": 0},
               {"case": "hc", "kind": "clean", "split": "holdout", "ok": True, "false_blocking": 2}]
        s = E.summarize(res)
        self.assertEqual(s["recall"], 0.667)                    # the headline still pools every case
        self.assertEqual((s["by_split"]["build"]["recall"], s["by_split"]["build"]["false_blocking"]), (1.0, None))
        ho = s["by_split"]["holdout"]
        self.assertEqual((ho["recall"], ho["caught"], ho["bug_cases"], ho["false_blocking"]), (0.0, 0, 1, 2))
        self.assertEqual(E._fmt_split("holdout", ho), "holdout: recall 0.0 (0/1 bug cases), false blocking 2 on 1 clean cases")
        self.assertIn("recall n/a (no bug cases)", E._fmt_split("holdout", E.summarize(res[3:])["by_split"]["holdout"]))
        self.assertNotIn("holdout", E.summarize(res[:2])["by_split"])
        # rows written before splits existed have no by_split; RESULTS.md must still render them
        orig = E.EVAL_DIR
        E.EVAL_DIR = tempfile.mkdtemp(prefix="crucible-evalres-")
        try:
            old = {"at": "2026-11-06T01:25", "label": "old", "recall": 0.917, "recall_any_severity": 1.0,
                   "false_blocking": 0, "true_dropped": 3}
            open(os.path.join(E.EVAL_DIR, "history.jsonl"), "w").write(json.dumps(old) + "\n")
            E.write_results("new", {"cases": 4}, s, [dict(r, kept=1, dropped=0, blocking=1, cost=0) for r in res])
            md = open(os.path.join(E.EVAL_DIR, "RESULTS.md")).read()
            self.assertIn("  - holdout: recall 0.0 (0/1 bug cases), false blocking 2 on 1 clean cases", md)
            self.assertIn("| h1 | bug | holdout | caught (non-blocking) |", md)
            self.assertIn("| new | 4 | 1.0 (2/2) | 0.0 (0/1) |", md)
            self.assertIn("| old | ? | 0.917 | – |", md)
            # a partial run appends its row but leaves the full run's RESULTS.md alone
            E.write_results("ho", {"cases": 2, "split": "holdout"}, E.summarize(res[2:]), res[2:], partial=True)
            self.assertEqual(open(os.path.join(E.EVAL_DIR, "RESULTS.md")).read(), md)
            E.write_results("full2", {"cases": 4}, s, [dict(r, kept=1, dropped=0, blocking=1, cost=0) for r in res])
            md = open(os.path.join(E.EVAL_DIR, "RESULTS.md")).read()
            self.assertIn("| ho | 2, holdout only | – | 0.0 (0/1) |", md)
        finally:
            shutil.rmtree(E.EVAL_DIR, ignore_errors=True)
            E.EVAL_DIR = orig


class TestMapLine(unittest.TestCase):
    def test_insert_delete_and_replace_hunks(self):
        self.assertEqual(D.map_line([(20, 0, 21, 2)], 20), 20)   # insertion after line 20 leaves line 20 alone
        self.assertEqual(D.map_line([(20, 0, 21, 2)], 21), 23)
        self.assertEqual(D.map_line([(6, 2, 5, 0)], 10), 8)      # deleting lines 6-7 moves later lines up by 2
        self.assertIsNone(D.map_line([(6, 2, 5, 0)], 6))
        self.assertEqual(D.map_line([(6, 1, 6, 3)], 9), 11)      # 1 line replaced by 3
        self.assertEqual(D.map_line([(6, 1, 6, 3)], 5), 5)


class TestSelfReviewFixes(unittest.TestCase):
    def test_issue_and_required_line_patterns_agree(self):
        for line in ("Closes #12", "Related issue: #34697", "Related to #5", "Refs #9", "Issue: #3", "**Fixes** #4",
                     "Resolves https://github.com/o/r/issues/8"):
            self.assertTrue(S.REQUIRED_LINE_RX.match(line), line)
            self.assertIsNotNone(R.linked_issue(line), line)

    def test_linked_issues_order_and_dedupe(self):
        self.assertEqual(R.linked_issues("Refs #2693. Closes #2823. Fixes #2823."), [2693, 2823])


class TestResolveIssue(unittest.TestCase):
    def test_skips_prs_and_trusts_unknown(self):
        orig = (R.gh_json, R.upstream_slug)
        data = {2693: {"pull_request": {}}, 2823: {"state": "open"}}
        R.gh_json = lambda path: data.get(int(path.rsplit("/", 1)[1]))
        R.upstream_slug = lambda repo: "o/r"
        try:
            self.assertEqual(R.resolve_issue(".", [2693, 2823]), (2823, [2693]))
            self.assertEqual(R.resolve_issue(".", [2693]), (None, [2693]))
            self.assertEqual(R.resolve_issue(".", [999]), (999, []))      # gh can't tell: trust the link
            R.upstream_slug = lambda repo: None
            self.assertEqual(R.resolve_issue(".", [2693]), (2693, []))    # no GitHub remote: first link
        finally:
            R.gh_json, R.upstream_slug = orig

    def test_bare_issue_url_line_survives_polish(self):
        body, restored = S.keep_required_lines("Fix x.\n\nhttps://github.com/o/r/issues/8", "Fix x, tidier.")
        self.assertEqual(restored, ["https://github.com/o/r/issues/8"])

    def test_recheck_prompt_differs_from_first_verification(self):
        f = {"title": "t", "file": "a.js", "line": 1, "severity": "low", "wrong_if": "w"}
        self.assertNotEqual(V.verify_prompt(f, "code"), V.verify_prompt(f, "code", "files changed since: b.js"))


class TestQuotedDiffPaths(unittest.TestCase):
    """git C-quotes non-ASCII names and tab-terminates names with spaces; parse must return the real path."""
    def test_real_git_diff_paths(self):
        d = make_repo({"café.py": "a\n", "a b.py": "a\n", 'q"t.py': "a\n", "keep.png": "x"},
                      {"café.py": "b\n", "a b.py": "b\n", 'q"t.py': "b\n", "新.py": "n\n", "keep.png": None,
                       "d e.png": "\x00\x01"})
        out = subprocess.run(["git", "-c", "core.quotepath=true", "diff", "main", "fix"], cwd=d,
                             capture_output=True, text=True).stdout
        files = {f["path"]: f for f in D.parse(out)}
        self.assertEqual(set(files), {"café.py", "a b.py", 'q"t.py', "新.py", "keep.png", "d e.png"})
        self.assertEqual(files["café.py"]["old_path"], "café.py")
        self.assertEqual(files["a b.py"]["old_path"], "a b.py")
        self.assertTrue(files["新.py"]["added"])
        self.assertTrue(files["keep.png"]["deleted"])
        self.assertEqual(files["café.py"]["hunks"][0]["lines"][-1][:2], ("+", "b"))

    def test_binary_names_with_and_and_deleted_binaries(self):
        """self-review de472ed (verifier side finding): ' and ' inside a binary name split the path wrongly."""
        d = make_repo({"p and q.png": "\x00a", "gone.bin": "\x00z"},
                      {"p and q.png": "\x00b", "gone.bin": None, "p and b/q.png": "\x00n"})
        files = {f["path"]: f for f in D.parse(sh(d, "git", "diff", "main", "fix"))}
        self.assertEqual(set(files), {"p and q.png", "gone.bin", "p and b/q.png"})
        self.assertTrue(files["gone.bin"]["deleted"] and files["gone.bin"]["binary"])
        self.assertTrue(files["p and b/q.png"]["added"] and not files["p and q.png"]["added"])

    def test_quoted_header_fallback_and_binary_line(self):
        self.assertEqual(D.parse('diff --git "a/caf\\303\\251 x" "b/caf\\303\\251 x"\nold mode 100644\nnew mode 100755')[0]["path"],
                         "café x")
        self.assertEqual(D.parse('diff --git "a/x\\303\\251.png" "b/x\\303\\251.png"\n'
                                 'Binary files /dev/null and "b/x\\303\\251.png" differ')[0]["path"], "xé.png")
        self.assertEqual(D._git_path('"b/t\\tab\\\\x"', "b/"), "t\tab\\x")


class TestRequiredLineReworded(unittest.TestCase):
    """DRG-79 (bvh-947, 2026-11-10): the rewrite turned "Fixes #947" into "Fix #947" and the restore added a second line."""
    def test_reworded_link_line_is_replaced_not_duplicated(self):
        body, restored = S.keep_required_lines("Fixes #947\n\nWorker errors now reject.",
                                               "Worker errors now reject the promise.\n\nFix #947")
        self.assertEqual(restored, ["Fixes #947"])
        self.assertEqual(body, "Worker errors now reject the promise.\n\nFixes #947")

    def test_reworded_bold_and_url_forms(self):
        body, _ = S.keep_required_lines("Text.\n\nCloses #5", "Better text.\n\n**Resolves:** #5.")
        self.assertEqual(body.count("#5"), 1)
        self.assertTrue(body.endswith("Closes #5"))
        body, _ = S.keep_required_lines("Text.\n\nhttps://github.com/o/r/issues/8",
                                        "Better.\n\n- Part of [#8](https://github.com/o/r/issues/8)")
        self.assertEqual(body, "Better.\n\nhttps://github.com/o/r/issues/8")

    def test_sentence_mentioning_the_issue_keeps_its_text(self):
        body, restored = S.keep_required_lines("Fixes #947\n\nx", "This fixes #947 by rejecting worker errors.")
        self.assertEqual(restored, ["Fixes #947"])
        self.assertIn("by rejecting worker errors", body)
        self.assertTrue(body.startswith("Fixes #947\n\n"))

    def test_negations_and_contrasts_are_not_link_lines(self):
        """self-review de472ed: a short line that says something else about the issue must survive."""
        for line in ["Unrelated to #947", "Does not fix #947.", "Not fixing #947", "Reverts #947", "Follow-up to #947",
                     "Duplicate of #947", "Fixes: #12, #13 is separate"]:
            self.assertFalse(S._is_link_line(line), line)
        for line in ["Fix #947", "**Resolves:** #947.", "- Part of [#8](https://github.com/o/r/issues/8)",
                     "Closes #1 and #2", "#947", "Related to: #5", "See also https://github.com/o/r/issues/8"]:
            self.assertTrue(S._is_link_line(line), line)
        body, _ = S.keep_required_lines("Related to #947\n\nbody", "Body text.\n\nDoes not fix #947.")
        self.assertIn("Does not fix #947.", body)
        self.assertTrue(body.startswith("Related to #947\n\n"))  # it was first in the original

    def test_this_repos_url_and_hash_form_are_the_same_issue(self):
        """self-review 3a4ab90: "Closes <url of #12>" reworded to "Closes #12" must not come back as a second line."""
        body, _ = S.keep_required_lines("Closes https://github.com/o/r/issues/12\n\nBody.", "Body, better.\n\nCloses #12",
                                        slug="O/r")
        self.assertEqual(body, "Body, better.\n\nCloses https://github.com/o/r/issues/12")

    def test_link_line_match_is_linear(self):
        import time
        t = time.time()
        for line in ["Fix https://x" + "#1" * 5000 + " !", "Fix " + "#1 " * 5000 + "x", "Fix [" + "a" * 5000]:
            self.assertFalse(S._is_link_line(line))
        self.assertLess(time.time() - t, 1.0)

    def test_another_repos_issue_with_the_same_number_is_kept(self):
        body, _ = S.keep_required_lines("Closes #12\n\nBody.\n\nSee also https://github.com/other/repo/issues/12",
                                        "Body, polished.\n\nSee also https://github.com/other/repo/issues/12")
        self.assertIn("other/repo/issues/12", body)
        self.assertTrue(body.startswith("Closes #12\n\n"))

    def test_other_issue_and_verbatim_lines_untouched(self):
        body, _ = S.keep_required_lines("Closes #1\nFixes #2\n\nx", "Closes #1\n\nFix #3\n\ny")
        self.assertIn("Fix #3", body)
        self.assertEqual(body.count("Closes #1"), 1)
        self.assertTrue(body.endswith("Fixes #2"))


class TestRequiredLinesNegative(unittest.TestCase):
    def test_prose_mentioning_an_issue_is_not_required(self):
        self.assertEqual(S.keep_required_lines("As discussed in https://github.com/o/r/issues/8 we fix x.", "We fix x.")[1], [])
        self.assertEqual(S.keep_required_lines("This overlaps #12.", "Overlap noted.")[1], [])


class TestUnclaimedPR(unittest.TestCase):
    def test_linked_pr_only_warns(self):
        orig = (R.gh_json, R.upstream_slug)
        R.gh_json = lambda path: {"pull_request": {"url": "x"}, "state": "open"}
        R.upstream_slug = lambda repo: "o/r"
        try:
            it = R.unclaimed(".", 5, "me")
            self.assertEqual(it["status"], "warn")
            self.assertIn("pull request", it["evidence"])
        finally:
            R.gh_json, R.upstream_slug = orig


class TestClaimOwner(unittest.TestCase):
    """The claim checks skipped a hard-coded maintainer handle, so for anyone else their own assignment on the issue
    failed "issue still unclaimed". They now skip the person running crucible."""

    def test_own_assignment_passes_and_someone_elses_fails(self):
        issue = {"state": "open", "assignees": [{"login": "alice"}]}
        orig = (R.gh_json, R.upstream_slug, os.environ.pop("CRUCIBLE_GH_USER", None))
        R.gh_json = lambda path, check=False: {"login": "alice"} if path == "user" else [] if "timeline" in path else issue
        R.upstream_slug = lambda repo: "o/r"
        try:
            self.assertEqual(R.current_login(), "alice")
            self.assertEqual(R.unclaimed(".", 5, R.current_login())["status"], "pass")
            os.environ["CRUCIBLE_GH_USER"] = "bob"                 # the override wins over gh
            self.assertEqual(R.current_login(), "bob")
            it = R.unclaimed(".", 5, R.current_login())
            self.assertEqual(it["status"], "fail")
            self.assertIn("assigned to ['alice']", it["evidence"])
            os.environ.pop("CRUCIBLE_GH_USER")
            R.gh_json = lambda path, check=False: None             # gh not logged in: nobody is skipped
            self.assertIsNone(R.current_login())
        finally:
            R.gh_json, R.upstream_slug = orig[0], orig[1]
            if orig[2] is not None:
                os.environ["CRUCIBLE_GH_USER"] = orig[2]
            else:
                os.environ.pop("CRUCIBLE_GH_USER", None)

    def test_login_case_and_unknown_login_hint(self):
        issue = {"state": "open", "assignees": [{"login": "alice"}]}
        orig = (R.gh_json, R.upstream_slug)
        R.gh_json = lambda path, check=False: [] if "timeline" in path else issue
        R.upstream_slug = lambda repo: "o/r"
        try:
            self.assertEqual(R.unclaimed(".", 5, "Alice")["status"], "pass")      # logins are case-insensitive
            it = R.unclaimed(".", 5, None)                                       # nobody known: say how to fix it
            self.assertEqual(it["status"], "fail")
            self.assertIn("CRUCIBLE_GH_USER", it["evidence"])
            self.assertNotIn("CRUCIBLE_GH_USER", R.unclaimed(".", 5, "bob")["evidence"])
        finally:
            R.gh_json, R.upstream_slug = orig

    def test_gh_not_installed_is_a_failed_call(self):
        # a stranger without gh: the review used to end in "FileNotFoundError: gh" (self-review, dropped as pre-existing)
        from unittest import mock

        for exc in (FileNotFoundError("gh"), subprocess.TimeoutExpired(["gh"], 120)):
            def no_gh(*a, **k):
                raise exc
            with mock.patch.object(U.subprocess, "run", no_gh):
                self.assertIsNone(U.gh_json("user"))
                with self.assertRaises(U.Failed):
                    U.gh_json("user", check=True)

    def test_missing_gh_is_an_unknown_login(self):
        from unittest import mock
        env = os.environ.pop("CRUCIBLE_GH_USER", None)

        def no_gh(*a, **k):
            raise FileNotFoundError("gh")
        try:
            with mock.patch.object(U.subprocess, "run", no_gh):
                self.assertIsNone(R.current_login())
        finally:
            if env is not None:
                os.environ["CRUCIBLE_GH_USER"] = env

    def _moved_base_fixture(self):
        """An upstream repo, a clone whose branch `fix` changes a.py off upstream/main, and a helper that lands a
        commit on upstream's main AFTER the clone's last fetch (so origin/main in the clone is stale)."""
        up = make_repo({"a.py": "x = 1\n", "b.py": "y = 1\n"})
        clone = tempfile.mkdtemp(prefix="crucible-clone-")
        subprocess.run(["git", "clone", "-q", up, clone], check=True)
        sh(clone, "git", "config", "user.email", "t@t"); sh(clone, "git", "config", "user.name", "t")
        sh(clone, "git", "checkout", "-qb", "fix")
        open(os.path.join(clone, "a.py"), "w").write("x = 2\n")
        sh(clone, "git", "commit", "-qam", "fix")
        base = sh(clone, "git", "merge-base", "origin/main", "HEAD")

        def land(path, text):
            open(os.path.join(up, path), "w").write(text)
            sh(up, "git", "commit", "-qam", f"upstream edits {path}")
            return sh(up, "git", "rev-parse", "HEAD")
        return up, clone, base, land

    def test_base_moved_fires_when_upstream_changed_a_touched_file_after_the_fetch(self):
        up, clone, base, land = self._moved_base_fixture()
        before = sh(clone, "git", "rev-parse", "origin/main")
        tip = land("a.py", "x = 3\n")
        r = R.base_moved(clone, "origin/main", base)
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("a.py", r["evidence"]); self.assertIn(tip[:10], r["evidence"]); self.assertIn("1 commit", r["evidence"])
        # the fetch is by URL: the clone's tracking ref and FETCH_HEAD are untouched
        self.assertEqual(sh(clone, "git", "rev-parse", "origin/main"), before)
        self.assertFalse(os.path.exists(os.path.join(clone, ".git", "FETCH_HEAD")))

    def test_base_moved_passes_when_unchanged_or_moved_elsewhere(self):
        up, clone, base, land = self._moved_base_fixture()
        r = R.base_moved(clone, "origin/main", base)
        self.assertEqual(r["status"], "pass", r); self.assertIn("still at the merge-base", r["evidence"])
        land("b.py", "y = 2\n")                                  # moved, but not in a file the change touches
        r = R.base_moved(clone, "origin/main", base)
        self.assertEqual(r["status"], "pass", r); self.assertIn("none in the files", r["evidence"])

    def test_base_moved_rewritten_unreachable_and_local_bases(self):
        up, clone, base, land = self._moved_base_fixture()
        sh(up, "git", "commit", "-q", "--amend", "-m", "rewritten")       # force-pushed base: merge-base gone from it
        r = R.base_moved(clone, "origin/main", base)
        self.assertEqual(r["status"], "warn", r); self.assertIn("rewritten", r["evidence"])
        self.assertEqual(R.base_moved(clone, "main", base)["status"], "na")      # local ref / SHA: na
        self.assertEqual(R.base_moved(clone, None, base)["status"], "na")
        r = R.base_moved(clone, "origin/gone", base)
        self.assertEqual(r["status"], "warn", r); self.assertIn("no branch", r["evidence"])
        sh(clone, "git", "remote", "set-url", "origin", os.path.join(up, "missing"))
        r = R.base_moved(clone, "origin/main", base)
        self.assertEqual(r["status"], "warn", r); self.assertIn("could not reach", r["evidence"])

    def test_base_moved_meets_renamed_and_quoted_paths(self):
        # self-review CR-8dec074c: upstream edits the old name of a file the change renamed, and a non-ASCII name
        # (C-quoted by `git diff --name-only` without -z); both used to read as "none in the files"
        up = make_repo({"old.py": "x = 1\n", "café.py": "c = 1\n", "b.py": "y = 1\n"})
        clone = tempfile.mkdtemp(prefix="crucible-clone-")
        subprocess.run(["git", "clone", "-q", up, clone], check=True)
        sh(clone, "git", "config", "user.email", "t@t"); sh(clone, "git", "config", "user.name", "t")
        sh(clone, "git", "checkout", "-qb", "fix")
        sh(clone, "git", "mv", "old.py", "new.py")
        open(os.path.join(clone, "café.py"), "w").write("c = 2\n")
        sh(clone, "git", "commit", "-qam", "rename + edit")
        base = sh(clone, "git", "merge-base", "origin/main", "HEAD")
        for path, text in (("old.py", "x = 3\n"), ("café.py", "c = 3\n")):
            open(os.path.join(up, path), "w").write(text)
        sh(up, "git", "commit", "-qam", "upstream edits")
        r = R.base_moved(clone, "origin/main", base)
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("old.py", r["evidence"]); self.assertIn("café.py", r["evidence"]); self.assertIn("2 of them", r["evidence"])

    def test_base_moved_slashed_branch_and_unfetchable_tip(self):
        up, clone, base, land = self._moved_base_fixture()
        sh(up, "git", "branch", "feature/x", "main"); sh(clone, "git", "fetch", "-q", "origin")
        self.assertEqual(R.base_moved(clone, "origin/feature/x", base)["status"], "pass")
        # self-review CR-bc4e60e6: ls-remote sees a tip the fetch can't bring (a push between the two calls, a drop)
        orig = R._remote_git
        R._remote_git = lambda repo, *a: ("f" * 40 + "\trefs/heads/main") if a[0] == "ls-remote" else None
        try:
            r = R.base_moved(clone, "origin/main", base)
        finally:
            R._remote_git = orig
        self.assertEqual(r["status"], "warn", r); self.assertIn("couldn't be fetched", r["evidence"])

    def test_remote_git_runs_without_a_controlling_terminal(self):
        # self-review CR-3f1c7fbd: ssh prompts on /dev/tty despite GIT_TERMINAL_PROMPT=0; a new session has no tty
        seen = {}
        orig = R.subprocess.run
        R.subprocess.run = lambda *a, **k: seen.update(k) or subprocess.CompletedProcess(a, 0, "", "")
        try:
            R._remote_git(".", "ls-remote", "origin")
        finally:
            R.subprocess.run = orig
        self.assertTrue(seen.get("start_new_session")); self.assertEqual(seen["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_evaluate_runs_base_moved_with_the_base_ref_unless_offline(self):
        up, clone, base, land = self._moved_base_fixture()
        land("a.py", "x = 3\n")
        files = [{"path": "a.py", "hunks": []}]
        orig = (R.unclaimed, R.overlapping_prs, R.resolve_issue)
        R.unclaimed = lambda repo, issue, me=None: R._item("issue still unclaimed", "pass", "")
        R.overlapping_prs = lambda repo, files, me=None: R._item("no open PR changes the same lines", "pass", "")
        R.resolve_issue = lambda repo, numbers: (None, [])
        try:
            item = lambda res: next(i for i in res["items"] if i["item"].startswith("base branch"))
            self.assertEqual(item(R.evaluate(clone, "o__r", base, files, me="t", base_ref="origin/main"))["status"], "warn")
            self.assertEqual(item(R.evaluate(clone, "o__r", base, files, offline=True, base_ref="origin/main"))["status"], "na")
        finally:
            R.unclaimed, R.overlapping_prs, R.resolve_issue = orig

    def test_evaluate_passes_the_login_to_both_claim_checks(self):
        # self-review CR-a8ea6b56: the wiring from evaluate() to the two checks had no test
        seen, env = {}, os.environ.pop("CRUCIBLE_GH_USER", None)
        orig = (R.gh_json, R.upstream_slug, R.unclaimed, R.overlapping_prs, R.resolve_issue)
        R.gh_json = lambda path, check=False: {"login": "alice"} if path == "user" else None

        def stub(key, name):
            def check(repo, arg, me=None):
                seen[key] = me
                return R._item(name, "pass", "")
            return check
        R.unclaimed = stub("unclaimed", "issue still unclaimed")
        R.overlapping_prs = stub("overlap", "no open PR changes the same lines")
        R.resolve_issue = lambda repo, numbers: (None, [])
        try:
            with tempfile.TemporaryDirectory() as d:
                subprocess.run(["git", "init", "-q", "-b", "main", d], check=True)
                subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                                "--allow-empty", "-m", "base"], check=True)
                R.upstream_slug = lambda repo: "o/r"
                R.evaluate(d, "o__r", "main", [])
                self.assertEqual(seen, {"unclaimed": "alice", "overlap": "alice"})
                seen.clear()
                R.upstream_slug = lambda repo: None               # no GitHub remote: no login lookup at all
                R.gh_json = lambda path, check=False: self.fail(f"unexpected gh call {path}")
                R.evaluate(d, "o__r", "main", [])
                self.assertEqual(seen, {"unclaimed": None, "overlap": None})
        finally:
            R.gh_json, R.upstream_slug, R.unclaimed, R.overlapping_prs, R.resolve_issue = orig
            if env is not None:
                os.environ["CRUCIBLE_GH_USER"] = env

    def test_offline_makes_no_login_call(self):
        calls = []
        orig = R.gh_json
        R.gh_json = lambda path, check=False: calls.append(path)
        try:
            with tempfile.TemporaryDirectory() as d:
                subprocess.run(["git", "init", "-q", "-b", "main", d], check=True)
                subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                                "--allow-empty", "-m", "base"], check=True)
                R.evaluate(d, "o__r", "main", [], offline=True)
            self.assertEqual(calls, [])
        finally:
            R.gh_json = orig


class TestOverlappingPRs(unittest.TestCase):
    """Real-use bug k: the competing-PR check only looked at PRs that reference the linked issue, so it missed
    Heroic #5776, which fixes a neighbouring issue in the same comparators."""

    @staticmethod
    def our_diff(changed_at=380):
        """A real --unified=5 diff, as review.py makes it: base lines changed_at..changed_at+1 replaced, a new file,
        and a lockfile. The hunk header spans 5 context lines each side; only the 2 changed lines may count."""
        base = [f"l{i}\n" for i in range(1, 501)]
        new = base[:changed_at - 1] + ["x\n", "y\n", "z\n"] + base[changed_at + 1:]
        d = make_repo({"src/Library.tsx": "".join(base), "pnpm-lock.yaml": "a\n"},
                      {"src/Library.tsx": "".join(new), "pnpm-lock.yaml": "b\n", "src/new_helper.ts": "export {}\n"})
        return D.parse(U.git(d, "diff", "--unified=5", "main..HEAD"))

    def setUp(self):
        self.OURS = self.our_diff()
        self.assertEqual(sorted(f["path"] for f in self.OURS), ["pnpm-lock.yaml", "src/Library.tsx", "src/new_helper.ts"])

    def stub(self, pages, patches):
        calls = []

        def gh(*args):
            calls.append(args)
            if args[0] == "graphql":
                after = next((a.split("=", 1)[1] for a in args if a.startswith("after=")), None)
                return pages.get(after)
            n = int(args[0].split("/pulls/")[1].split("/")[0])
            return patches.get(n)
        orig = (R.gh_json, R.upstream_slug)
        R.gh_json, R.upstream_slug = gh, (lambda repo: "o/r")
        self.addCleanup(lambda: setattr(R, "gh_json", orig[0]) or setattr(R, "upstream_slug", orig[1]))
        return calls

    @staticmethod
    def page(nodes, total, cursor=None):
        return {"data": {"repository": {"pullRequests": {
            "totalCount": total, "pageInfo": {"hasNextPage": bool(cursor), "endCursor": cursor},
            "nodes": [{"number": n, "url": f"u/{n}", "isDraft": False, "author": {"login": who, "__typename": typ},
                       "files": {"nodes": [{"path": p} for p in paths]}} for n, who, typ, paths in nodes]}}}}

    def test_focused_line_overlap_ranks_first_and_noise_is_filtered(self):
        giant = ["src/Library.tsx"] + [f"src/f{i}.ts" for i in range(60)]
        self.stub({None: self.page([(6045, "a", "User", giant),
                                    (7001, "dependabot", "Bot", ["src/Library.tsx"]),
                                    (7002, "me", "User", ["src/Library.tsx"]),
                                    (7003, "b", "User", ["src/Library.tsx", "x.ts"]),     # same file, far away
                                    (7004, "c", "User", ["pnpm-lock.yaml"])], 105, "c1"),
                   "c1": self.page([(5776, "d", "User", ["src/Library.tsx", "src/Console.tsx"])], 105)},
                  {6045: [{"filename": "src/Library.tsx", "patch": "@@ -378,6 +378,6 @@ x"}],
                   7003: [{"filename": "src/Library.tsx", "patch": "@@ -10,7 +10,8 @@ y\n@@ -900,6 +901,6 @@"}],
                   5776: [{"filename": "src/Library.tsx", "patch": "@@ -375,11 +375,12 @@ sort"}]})
        it = R.overlapping_prs(".", self.OURS, "me")
        self.assertEqual(it["status"], "warn")
        ev = it["evidence"]
        self.assertTrue(ev.startswith("#5776 by d (1 of its 2 files)"), ev)   # the focused PR leads
        self.assertIn("#6045", ev)
        self.assertLess(ev.index("#5776"), ev.index("#6045"))
        for skipped in ("#7001", "#7002", "#7004"):                          # bot, our own PR, lockfile only
            self.assertNotIn(skipped, ev)
        self.assertIn("1 touch the same files elsewhere (#7003)", ev)
        self.assertIn("checked 6 of 105 open PRs", ev)

    def test_margin_is_their_3_context_lines_not_our_unified_5(self):
        # we change base 380-381; a PR hunk covering 371-376 is 4 lines away. Our --unified=5 header (375-386)
        # would have met it; only our changed lines may count.
        self.stub({None: self.page([(7006, "f", "User", ["src/Library.tsx"])], 1)},
                  {7006: [{"filename": "src/Library.tsx", "patch": "@@ -371,6 +371,6 @@"}]})
        self.assertEqual(R.overlapping_prs(".", self.OURS, "me")["status"], "pass")
        self.stub({None: self.page([(7006, "f", "User", ["src/Library.tsx"])], 1)},
                  {7006: [{"filename": "src/Library.tsx", "patch": "@@ -372,9 +372,9 @@"}]})   # 372-380
        self.assertEqual(R.overlapping_prs(".", self.OURS, "me")["status"], "warn")

    def test_pure_insertion_anchors_on_the_next_base_line(self):
        hunk = D.parse("diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -12,0 +13,2 @@\n+a\n+b\n")[0]["hunks"]
        self.assertEqual(R._changed_old_lines(hunk), {13})

    def test_patchless_shared_file_is_not_compared_not_distant(self):
        self.stub({None: self.page([(7007, "g", "User", ["src/Library.tsx"])], 1)},
                  {7007: [{"filename": "src/Library.tsx"}]})                    # too large: GitHub sends no patch
        it = R.overlapping_prs(".", self.OURS, "me")
        self.assertEqual(it["status"], "warn")
        self.assertIn("1 couldn't be compared, no readable patch (#7007)", it["evidence"])
        self.assertNotIn("elsewhere", it["evidence"])
        self.stub({None: self.page([(7008, "h", "User", ["src/Library.tsx"])], 1)},
                  {7008: [{"filename": "other.ts", "patch": "@@ -1,3 +1,3 @@"}]})   # path past the REST page
        self.assertIn("couldn't be compared", R.overlapping_prs(".", self.OURS, "me")["evidence"])
        self.stub({None: self.page([(7009, "i", "User", ["src/Library.tsx"])], 1)},
                  {7009: [{"filename": "src/Library.tsx", "status": "renamed", "changes": 0}]})  # pure rename
        self.assertEqual(R.overlapping_prs(".", self.OURS, "me")["status"], "pass")
        self.stub({None: self.page([(7010, "j", "User", ["src/Library.tsx"])], 1)},
                  {7010: [{"filename": "src/Library.tsx", "status": "modified", "changes": 0}]})  # binary looks so
        self.assertIn("couldn't be compared", R.overlapping_prs(".", self.OURS, "me")["evidence"])

    def test_candidates_past_the_cap_are_reported_not_compared(self):
        n = R.OVERLAP_CANDIDATES + 3
        far = {k: [{"filename": "src/Library.tsx", "patch": "@@ -10,6 +10,6 @@"}] for k in range(1, n + 1)}
        calls = self.stub({None: self.page([(k, "u", "User", ["src/Library.tsx"]) for k in range(1, n + 1)], n)}, far)
        it = R.overlapping_prs(".", self.OURS, "me")
        self.assertEqual(it["status"], "warn")                              # 3 PRs were never compared
        self.assertIn(f"{R.OVERLAP_CANDIDATES} touch the same files elsewhere", it["evidence"])
        self.assertIn(f"3 more share a file but weren't compared line by line (#{n - 2}, #{n - 1}, #{n})", it["evidence"])
        self.assertEqual(sum(1 for c in calls if c[0] != "graphql"), R.OVERLAP_CANDIDATES)

    def test_graphql_variables_are_sent_as_strings(self):
        calls = self.stub({None: self.page([], 0)}, {})
        R.open_prs("2048/true")
        args = calls[0]
        self.assertIn("owner=2048", args)
        self.assertEqual(args[args.index("owner=2048") - 1], "-f")
        self.assertEqual(args[args.index("name=true") - 1], "-f")

    def test_pass_when_only_distant_hunks_and_new_file_collision_counts(self):
        self.stub({None: self.page([(7003, "b", "User", ["src/Library.tsx"])], 1)},
                  {7003: [{"filename": "src/Library.tsx", "patch": "@@ -900,6 +901,6 @@"}]})
        self.assertEqual(R.overlapping_prs(".", self.OURS, "me")["status"], "pass")
        self.stub({None: self.page([(7005, "e", "User", ["src/new_helper.ts"])], 1)},
                  {7005: [{"filename": "src/new_helper.ts", "patch": "@@ -0,0 +1,40 @@"}]})
        it = R.overlapping_prs(".", self.OURS, "me")
        self.assertEqual(it["status"], "warn")
        self.assertIn("#7005", it["evidence"])

    def test_own_pr_is_skipped_case_insensitively_and_unknown_login_says_so(self):
        # self-review CR-85a28de2: the unknown-login hint was only on the unclaimed check
        self.stub({None: self.page([(7005, "Alice", "User", ["src/new_helper.ts"])], 1)},
                  {7005: [{"filename": "src/new_helper.ts", "patch": "@@ -0,0 +1,40 @@"}]})
        self.assertEqual(R.overlapping_prs(".", self.OURS, "alice")["status"], "pass")
        it = R.overlapping_prs(".", self.OURS, None)
        self.assertEqual(it["status"], "warn")
        self.assertIn("CRUCIBLE_GH_USER", it["evidence"])
        self.assertNotIn("CRUCIBLE_GH_USER", R.overlapping_prs(".", self.OURS, "bob")["evidence"])

    def test_unreadable_api_warns_and_pages_are_capped(self):
        calls = self.stub({}, {})
        it = R.overlapping_prs(".", self.OURS, "me")
        self.assertEqual((it["status"], it["evidence"]), ("warn", "could not list open PRs on o/r"))
        self.assertEqual(len(calls), 2)                                     # one retry, then give up
        calls = self.stub({None: self.page([], 999, "c1"), "c1": self.page([], 999, "c2"),
                           "c2": self.page([], 999, "c3"), "c3": self.page([], 999, "c4")}, {})
        prs, total = R.open_prs("o/r")
        self.assertEqual((prs, total, len(calls)), ([], 999, R.OPEN_PR_PAGES))
        calls = self.stub({None: self.page([(7003, "b", "User", ["src/Library.tsx"])], 1)}, {})  # files call fails
        it = R.overlapping_prs(".", self.OURS, "me")
        self.assertEqual(it["status"], "warn")
        # An API failure (gamescope, 2026-11-06: REST quota out) is not a fact about the PR's patch
        self.assertIn("1 couldn't be fetched, the GitHub API call failed", it["evidence"])
        self.assertNotIn("no readable patch", it["evidence"])

    def test_patches_are_cached_by_head_sha(self):
        """Review rounds on a busy repo (gamescope: 151 open PRs, 70 sharing a file) used to refetch the same 20
        patches over REST every round. A PR's diff is fixed by its head SHA, so only a moved head is refetched."""
        def page(heads):
            pg = self.page([(n, "u", "User", ["src/Library.tsx"]) for n in sorted(heads)], len(heads))
            for node in pg["data"]["repository"]["pullRequests"]["nodes"]:
                node["headRefOid"] = heads[node["number"]]
            return pg
        near = [{"filename": "src/Library.tsx", "patch": "@@ -378,6 +378,6 @@"}]
        far = [{"filename": "src/Library.tsx", "patch": "@@ -10,6 +10,6 @@"}]
        rest = lambda calls: sorted(int(c[0].split("/pulls/")[1].split("/")[0]) for c in calls if c[0] != "graphql")
        calls = self.stub({None: page({8001: "a1", 8002: "b1"})}, {8001: far, 8002: far})
        self.assertEqual(R.overlapping_prs(".", self.OURS, "me")["status"], "pass")
        self.assertEqual(rest(calls), [8001, 8002])
        calls = self.stub({None: page({8001: "a1", 8002: "b1"})}, {8001: near, 8002: near})  # same heads
        self.assertEqual(R.overlapping_prs(".", self.OURS, "me")["status"], "pass")   # cached hunks, not refetched
        self.assertEqual(rest(calls), [])
        calls = self.stub({None: page({8001: "a1", 8002: "b2"})}, {8001: near, 8002: near})  # 8002 pushed again
        it = R.overlapping_prs(".", self.OURS, "me")
        self.assertEqual(rest(calls), [8002])
        self.assertTrue(it["evidence"].startswith("#8002 by u"), it["evidence"])
        # A failed fetch is never cached: the next round asks again
        calls = self.stub({None: page({8003: "c1"})}, {})
        self.assertIn("couldn't be fetched", R.overlapping_prs(".", self.OURS, "me")["evidence"])
        calls = self.stub({None: page({8003: "c1"})}, {8003: far})
        self.assertEqual(R.overlapping_prs(".", self.OURS, "me")["status"], "pass")
        self.assertEqual(rest(calls), [8003])
        # The cache is per repository
        calls = self.stub({None: page({8001: "a1"})}, {8001: far})
        orig = R.upstream_slug
        R.upstream_slug = lambda repo: "other/r"
        try:
            R.overlapping_prs(".", self.OURS, "me")
        finally:
            R.upstream_slug = orig
        self.assertEqual(rest(calls), [8001])

    def test_hunk_cache_expires_and_tolerates_bad_or_unwritable_files(self):
        far = [{"filename": "src/Library.tsx", "patch": "@@ -10,6 +10,6 @@"}]
        pg = self.page([(8101, "u", "User", ["src/Library.tsx"])], 1)
        pg["data"]["repository"]["pullRequests"]["nodes"][0]["headRefOid"] = "h1"
        rest = lambda calls: sum(1 for c in calls if c[0] != "graphql")
        calls = self.stub({None: pg}, {8101: far})
        R.overlapping_prs(".", self.OURS, "me")
        path = R._hunk_cache_path("o/r", 8101)
        entry = U.read_json(path)
        bad = [{**entry, "at": entry["at"] - R.HUNK_CACHE_TTL - 1}, {**entry, "at": "yesterday"}, [],   # expired,
               {**entry, "hunks": {"src/Library.tsx": 5}}, {**entry, "hunks": {"src/Library.tsx": [[7]]}}]  # edited
        for damaged in bad:
            U.write_json(path, damaged)
            calls = self.stub({None: pg}, {8101: far})
            self.assertEqual(R.overlapping_prs(".", self.OURS, "me")["status"], "pass")
            self.assertEqual(rest(calls), 1)
        calls = self.stub({None: pg}, {8101: far})                      # the refetch refreshed the entry
        R.overlapping_prs(".", self.OURS, "me")
        self.assertEqual(rest(calls), 0)
        # An unwritable cache (here a file where the directory should be) degrades to fetching, never fails
        orig = R.util.HOME
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "cache"), "w").close()
            R.util.HOME = d
            try:
                calls = self.stub({None: pg}, {8101: far})
                self.assertEqual(R.overlapping_prs(".", self.OURS, "me")["status"], "pass")
                self.assertEqual(rest(calls), 1)
            finally:
                R.util.HOME = orig

    def test_only_shared_files_is_na(self):
        self.stub({}, {})
        lock = [f for f in self.OURS if f["path"] == "pnpm-lock.yaml"]
        self.assertEqual(R.overlapping_prs(".", lock, "me")["status"], "na")


class TestRunReviewIncremental(unittest.TestCase):
    """run_review end to end with a stubbed model: round 1 full, round 2 incremental; a carried finding whose cited
    lines didn't change is re-checked against the later changes and dropped when the cheap verifier is sure."""

    def test_two_rounds(self):
        with tempfile.TemporaryDirectory() as d:
            repo, home = os.path.join(d, "r"), os.path.join(d, "home")
            os.makedirs(os.path.join(repo, "src"))
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")   # the user's git config can't change the fixture
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env).stdout.decode().strip()
            w = lambda p, t: open(os.path.join(repo, p), "w").write(t)
            g("init", "-q", "-b", "main"); w("src/a.js", "export const a = 1;\n"); w("src/b.js", "export const b = 1;\n")
            g("add", "-A"); g("commit", "-qm", "base"); g("checkout", "-qb", "x")
            w("src/a.js", "export const a = 1;\nexport function f(xs) { return xs[xs.length]; }\n")
            w("src/b.js", "export const b = 1;\nexport function g() { return 2; }\n")
            g("commit", "-qam", "add f and g")
            calls = []

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                calls.append((model, "findings" in schema["properties"], "changed since then" in prompt))
                if "findings" in schema["properties"]:
                    found = [] if "src/a.js" not in prompt else [
                        {"severity": "important", "file": "src/a.js", "line": 2, "title": "f reads past the end",
                         "problem": "xs[xs.length]", "caused_by_this_change": True, "reachable_in_real_use": True,
                         "wrong_if": "index < length", "fix": "length - 1"}]
                    if "src/b.js" in prompt and "export function g" in prompt:
                        found.append({"severity": "medium", "file": "src/b.js", "line": 2, "title": "g returns a constant",
                                      "problem": "callers expect the input back", "caused_by_this_change": True,
                                      "reachable_in_real_use": True, "wrong_if": "callers want 2", "fix": "return x"})
                    return {"summary": "s", "findings": found}, 0.01
                if "changed since then" in prompt:      # the re-check of the carried b.js finding: its caller changed
                    return {"keep": False, "severity": "medium", "method": "read", "actions": "read caller",
                            "evidence": "test/g.test.js now expects 2", "confidence": "high"}, 0.001
                return {"keep": True, "severity": "important" if "past the end" in prompt else "medium", "method": "read",
                        "actions": "read", "evidence": "seen", "confidence": "high"}, 0.001

            olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
            V.HOME = U.HOME = home
            os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
            V.claude = fake
            try:
                d1 = V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None)
                r1 = U.read_json(os.path.join(d1, "review.json"))
                self.assertEqual(r1["status"], "done", r1.get("reason"))
                self.assertEqual(sorted(f["file"] for f in r1["findings"]), ["src/a.js", "src/b.js"])
                # round 2: fix f in a.js and add a test for g in another file; b.js itself is untouched
                w("src/a.js", "export const a = 1;\nexport function f(xs) { return xs[xs.length - 1]; }\n")
                os.makedirs(os.path.join(repo, "test")); w("test/g.test.js", "import { g } from '../src/b.js';\n")
                g("add", "-A"); g("commit", "-qm", "fix f, test g")
                calls.clear()
                d2 = V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None)
                r2 = U.read_json(os.path.join(d2, "review.json"))
                self.assertEqual(r2["status"], "done", r2.get("reason"))
                self.assertEqual(r2["incremental"]["carried"], 1)            # g returns a constant (b.js untouched)
                self.assertEqual(r2["incremental"]["reverified"], 1)         # f reads past the end (a.js touched)
                self.assertTrue(any(c[2] for c in calls))                    # the re-check saw the later changes
                kept_titles = {f["title"] for f in r2["findings"]}
                self.assertNotIn("g returns a constant", kept_titles)        # dropped by the re-check
                self.assertIn("g returns a constant", {f["title"] for f in r2["dropped"]})
                self.assertTrue(r2["coverage"]["complete"])
            finally:
                V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
                if olds[3] is None:
                    os.environ.pop("CRUCIBLE_CACHE", None)
                else:
                    os.environ["CRUCIBLE_CACHE"] = olds[3]


class TestRunReviewAmended(unittest.TestCase):
    """Round 2 after `git commit --amend`: the reviewed commit is no ancestor of HEAD any more, but with the same
    merge-base only the files changed between the rounds are reviewed again (38 of 57 upstream reviews were full
    re-reviews of an amend)."""

    def test_recheck_of_a_carried_finding_is_scoped_to_the_whole_pr(self):
        """colyseus #1000 replay: the re-check read "caused by this change" as "since the last round" and dropped a
        true finding on a line round 1's commit added. Both re-check prompts now say the PR is base..HEAD."""
        with tempfile.TemporaryDirectory() as d:
            repo, home = os.path.join(d, "r"), os.path.join(d, "home")
            os.makedirs(os.path.join(repo, "src"))
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env).stdout.decode().strip()
            w = lambda p, t: open(os.path.join(repo, p), "w").write(t)
            g("init", "-q", "-b", "main"); w("src/a.js", "export const a = 1;\n"); w("src/b.js", "export const b = 1;\n")
            g("add", "-A"); g("commit", "-qm", "base"); g("checkout", "-qb", "x")
            base = g("rev-parse", "main")
            w("src/a.js", "export const a = 2;\n"); w("src/b.js", "export const b = 1;\nexport function g() { return 2; }\n")
            g("commit", "-qam", "change")
            verify = []

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                if "findings" in schema["properties"]:
                    found = [{"severity": "medium", "file": "src/b.js", "line": 2, "title": "g returns a constant",
                              "problem": "p", "caused_by_this_change": True, "reachable_in_real_use": True,
                              "wrong_if": "w", "fix": "f"}] if "export function g" in prompt else []
                    return {"summary": "s", "findings": found}, 0.01
                verify.append(prompt)
                return {"keep": True, "severity": "medium", "method": "read", "actions": "read", "evidence": "seen",
                        "confidence": "high"}, 0.001

            olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"), os.environ.get("CRUCIBLE_VERIFY_CHEAP"))
            V.HOME = U.HOME = home
            os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
            os.environ["CRUCIBLE_VERIFY_CHEAP"] = "cheap-model"
            V.claude = fake
            try:
                V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None)
                w("src/a.js", "export const a = 3;\n")
                g("commit", "-q", "--amend", "-am", "change")
                verify.clear()
                d2 = V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None)
                self.assertEqual((U.read_json(os.path.join(d2, "review.json")).get("incremental") or {}).get("carried"), 1)
                rechecks = [p for p in verify if "its cited lines are unchanged" in p]
                self.assertEqual(len(rechecks), 1)
                self.assertIn(f"the whole PR ({base[:10]}..HEAD)", rechecks[0])
            finally:
                V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
                for k, v in (("CRUCIBLE_CACHE", olds[3]), ("CRUCIBLE_VERIFY_CHEAP", olds[4])):
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_amended_big_catalog_raw_diff_stays_out_of_the_pass(self):
        with tempfile.TemporaryDirectory() as d:
            repo, home = os.path.join(d, "r"), os.path.join(d, "home")
            os.makedirs(os.path.join(repo, "po"))
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env).stdout.decode().strip()
            w = lambda p, t: open(os.path.join(repo, p), "w").write(t)
            po = lambda first: "".join(f'msgid "s{i}"\nmsgstr "{first if i == 0 else f"t{i}"}"\n\n' for i in range(150))
            g("init", "-q", "-b", "main"); w("a.js", "export const a = 1;\n"); w("po/fr.po", "")
            g("add", "-A"); g("commit", "-qm", "base"); g("checkout", "-qb", "x")
            w("a.js", "export const a = 2;\n"); w("po/fr.po", po("t0")); g("add", "-A"); g("commit", "-qm", "c")
            passes = []

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                if "findings" in schema["properties"]:
                    passes.append(prompt)
                    return {"summary": "s", "findings": []}, 0.01
                return {"keep": True, "severity": "low", "method": "read", "actions": "r", "evidence": "e",
                        "confidence": "high"}, 0.001

            olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
            V.HOME = U.HOME = home
            os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
            V.claude = fake
            try:
                V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, log=lambda *_: None)
                w("a.js", "export const a = 3;\n"); w("po/fr.po", po("u0"))
                g("commit", "-q", "--amend", "-am", "c")
                passes.clear()
                d2 = V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, log=lambda *_: None)
                self.assertTrue((U.read_json(os.path.join(d2, "review.json")).get("incremental") or {}).get("amended"))
                prompt = "\n".join(passes)
                self.assertIn('+msgstr "u0"', prompt)                 # the small inter-diff is reviewed raw
                self.assertIn("+export const a = 3;", prompt)
                self.assertNotIn('msgstr "t140"', prompt)             # but the catalog's 300-line base diff isn't context
            finally:
                V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
                if olds[3] is None:
                    os.environ.pop("CRUCIBLE_CACHE", None)
                else:
                    os.environ["CRUCIBLE_CACHE"] = olds[3]

    def test_absence_recheck_is_scoped_to_the_whole_pr(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            g = lambda *a: subprocess.run(["git", "-C", d, *a], check=True, capture_output=True, env=env).stdout.decode().strip()
            g("init", "-q"); open(os.path.join(d, "t.js"), "w").write("1\n"); g("add", "-A"); g("commit", "-qm", "a")
            prev = g("rev-parse", "HEAD")
            open(os.path.join(d, "t.js"), "w").write("2\n"); g("commit", "-qam", "b")
            text = V.anchor_since(d, prev, {"anchor_changed": ["t.js"]}, "f" * 40)
            self.assertIn("the whole PR (ffffffffff..HEAD)", text)
            self.assertIn("+2", text)


    def test_amend_is_incremental(self):
        with tempfile.TemporaryDirectory() as d:
            repo, home = os.path.join(d, "r"), os.path.join(d, "home")
            os.makedirs(os.path.join(repo, "src"))
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env).stdout.decode().strip()
            w = lambda p, t: open(os.path.join(repo, p), "w").write(t)
            g("init", "-q", "-b", "main"); w("src/a.js", "export const a = 1;\n"); w("src/b.js", "export const b = 1;\n")
            g("add", "-A"); g("commit", "-qm", "base"); g("checkout", "-qb", "x")
            w("src/a.js", "export const a = 1;\nexport function f(xs) { return xs[xs.length]; }\n")
            w("src/b.js", "export const b = 1;\nexport function g() { return 2; }\n")
            g("commit", "-qam", "add f and g")
            passes = []

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                if "findings" in schema["properties"]:
                    passes.append(prompt)
                    found = [{"severity": "medium", "file": "src/b.js", "line": 2, "title": "g returns a constant",
                              "problem": "callers expect the input back", "caused_by_this_change": True,
                              "reachable_in_real_use": True, "wrong_if": "callers want 2", "fix": "return x"}] \
                        if "export function g" in prompt else []
                    return {"summary": "s", "findings": found}, 0.01
                return {"keep": True, "severity": "medium", "method": "read", "actions": "read", "evidence": "seen",
                        "confidence": "high"}, 0.001

            olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
            V.HOME = U.HOME = home
            os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
            V.claude = fake
            try:
                d1 = V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, log=lambda *_: None)
                r1 = U.read_json(os.path.join(d1, "review.json"))
                self.assertEqual(r1["status"], "done", r1.get("reason"))
                self.assertNotIn("RE-REVIEW", passes[0])                    # a first round has no inter-diff
                # round 2: amend a.js only; the round-1 commit leaves HEAD's history
                w("src/a.js", "export const a = 1;\nexport function f(xs) { return xs[xs.length - 1]; }\n")
                g("commit", "-q", "--amend", "-am", "add f and g")
                passes.clear()
                d2 = V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, log=lambda *_: None)
                r2 = U.read_json(os.path.join(d2, "review.json"))
                self.assertEqual(r2["status"], "done", r2.get("reason"))
                inc = r2.get("incremental") or {}
                self.assertEqual((inc.get("from"), inc.get("files"), inc.get("amended")), (r1["sha"], ["src/a.js"], True))
                self.assertEqual(len(passes), 1)
                self.assertNotIn("export function g", passes[0])           # b.js's diff isn't sent again
                # DRG-63: the pass says its diff is the inter-diff of an amend, and carries a.js's whole change
                self.assertIn(f"INTER-DIFF {r1['sha'][:10]}..HEAD", passes[0])
                self.assertIn("amended or rebased", passes[0])
                self.assertIn("@@ -1 +1,2 @@", passes[0])                  # base..HEAD hunk of a.js, not the inter-diff's
                self.assertEqual(inc.get("carried"), 1)                     # b.js untouched by the amend
                self.assertIn("g returns a constant", {f["title"] for f in r2["findings"]})
                self.assertTrue(r2["coverage"]["complete"])
                # --full still reviews everything
                passes.clear()
                d3 = V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, full=True, force=True,
                                  log=lambda *_: None)
                self.assertNotIn("incremental", U.read_json(os.path.join(d3, "review.json")))
            finally:
                V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
                if olds[3] is None:
                    os.environ.pop("CRUCIBLE_CACHE", None)
                else:
                    os.environ["CRUCIBLE_CACHE"] = olds[3]


class TestRunReviewTranscribed(unittest.TestCase):
    """Bug l end to end: when the verifier answers in prose, a transcribed "holds" is kept as verified (and marked),
    a transcribed "does not hold" keeps the finding as unverified with that prose, and a transcribed re-check of a
    carried finding neither drops it nor marks it re-checked."""

    def test_transcribed_verdicts_never_drop(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            repo, home = os.path.join(d, "r"), os.path.join(d, "home")
            os.makedirs(os.path.join(repo, "src"))
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env).stdout.decode().strip()
            w = lambda p, t: open(os.path.join(repo, p), "w").write(t)
            g("init", "-q", "-b", "main"); w("src/a.js", "export const a = 1;\n"); w("src/b.js", "export const b = 1;\n")
            g("add", "-A"); g("commit", "-qm", "base"); g("checkout", "-qb", "x")
            w("src/a.js", "export const a = 1;\nexport function f(xs) { return xs[xs.length]; }\n")
            w("src/b.js", "export const b = 1;\nexport function g() { return 2; }\n")
            g("commit", "-qam", "add f and g")

            def finding(path, title):
                return {"severity": "medium", "file": path, "line": 2, "title": title, "problem": "p",
                        "caused_by_this_change": True, "reachable_in_real_use": True, "wrong_if": "w", "fix": "x"}

            transcribed = []

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                if "findings" in schema["properties"]:
                    return {"summary": "s", "findings": [finding(p, t) for p, t in
                            (("src/a.js", "f reads past the end"), ("src/b.js", "g returns a constant")) if p in prompt]}, 0
                if "Transcribe that verdict" in prompt:      # the salvage call: transcribe the prose it was given
                    transcribed.append(re.search(r"Claim: (.*?) \(at", prompt).group(1))
                    holds = "HOLDS" in prompt
                    return {"keep": holds, "severity": "medium", "confidence": "high", "method": "read",
                            "actions": "a", "evidence": "prose says " + ("it holds" if holds else "falsified")}, 0
                raise U.NoStructuredOutput("x", "Verdict: HOLDS" if "past the end" in prompt else "Verdict: falsified")

            with mock.patch.object(V, "HOME", home), mock.patch.object(U, "HOME", home), \
                    mock.patch.object(V, "claude", fake), mock.patch.dict(os.environ, {"CRUCIBLE_CACHE": os.path.join(home, "c"),
                                                           "CRUCIBLE_VERIFY_CHEAP": "cheap", "CRUCIBLE_VERIFY_MODEL": "strong"}):
                r = U.read_json(os.path.join(V.run_review(repo, "main", offline=True, skip_checks=True,
                                                          log=lambda *_: None), "review.json"))
                self.assertEqual(r["status"], "done", r.get("reason"))
                self.assertEqual(r["dropped"], [])
                by = {f["title"]: f["verification"] for f in r["findings"]}
                self.assertEqual(by["f reads past the end"]["status"], "verified")
                self.assertIn("transcribed", V.transcribed_note(by["f reads past the end"]))
                self.assertEqual(by["g returns a constant"]["status"], "unverified")
                self.assertIn("prose says falsified", by["g returns a constant"]["reason"])
                # round 2 touches only a.js: the b.js finding is carried and re-checked, and that re-check is transcribed
                w("src/a.js", "export const a = 1;\nexport function f(xs) { return xs[xs.length - 1]; }\n")
                g("commit", "-qam", "fix f")
                transcribed.clear()
                r2 = U.read_json(os.path.join(V.run_review(repo, "main", offline=True, skip_checks=True,
                                                           log=lambda *_: None), "review.json"))
                self.assertEqual(r2["status"], "done", r2.get("reason"))
                carried = [f for f in r2["findings"] if f["title"] == "g returns a constant"]
                self.assertEqual(len(carried), 1)
                self.assertIn("g returns a constant", transcribed)           # the re-check ran and was transcribed
                self.assertNotIn("rechecked", carried[0])
                self.assertEqual(carried[0]["verification"]["status"], "unverified")
                self.assertEqual(r2["dropped"], [])


class TestRunReviewAbsenceAnchor(unittest.TestCase):
    """ROADMAP item 1, the bug-l self-review case: "no test for the guard" cites the guard, its test lands in the test
    file, the guard's lines don't change. The old line-based carry kept the finding (and with one verify tier never
    re-checked it). Now it is re-verified with the test file's diff in front of the verifier, and dropped; a later
    round that leaves its anchor alone carries the remaining finding without a verify call."""

    def test_landed_test_drops_the_absence_finding(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            repo, home = os.path.join(d, "r"), os.path.join(d, "home")
            os.makedirs(os.path.join(repo, "tests"))
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env).stdout.decode().strip()
            w = lambda p, t: open(os.path.join(repo, p), "w").write(t)
            g("init", "-q", "-b", "main"); g("config", "core.quotepath", "true")    # git's default; hides nothing
            w("guard.py", "def ok(v):\n    return True\n"); w("tests/test_ü.py", "# tests\n")
            g("add", "-A"); g("commit", "-qm", "base"); g("checkout", "-qb", "x")
            w("guard.py", "def ok(v):\n    return not v.get('salvaged')\n"); g("commit", "-qam", "guard")
            verify_prompts = []

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                if "findings" in schema["properties"]:
                    if "BOOM" in prompt:
                        raise U.Failed("model call failed")
                    if "def ok" not in prompt:
                        return {"summary": "only the test file changed", "findings": []}, 0
                    return {"summary": "adds the salvaged guard, untested", "findings": [
                        {"severity": "low", "file": "guard.py", "line": 2, "title": "No test for the salvaged guard",
                         "problem": "p", "caused_by_this_change": True, "reachable_in_real_use": True, "wrong_if": "a test",
                         "fix": "add one", "anchor_files": ["tests/test_ü.py"]},
                        {"severity": "low", "file": "guard.py", "line": 1, "title": "ok() is a vague name",
                         "problem": "p", "caused_by_this_change": True, "reachable_in_real_use": True, "wrong_if": "w",
                         "fix": "rename"}]}, 0
                verify_prompts.append(prompt)
                landed = "test_salvaged_guard" in prompt          # the verifier was shown the landed test
                return {"keep": not landed, "severity": "low", "confidence": "high", "method": "read", "actions": "a",
                        "evidence": "tests/test_ü.py:2 covers it" if landed else "no test"}, 0

            with mock.patch.object(V, "HOME", home), mock.patch.object(U, "HOME", home), \
                    mock.patch.object(V, "claude", fake), mock.patch.dict(os.environ, {"CRUCIBLE_CACHE": os.path.join(home, "c")}):
                run = lambda: U.read_json(os.path.join(V.run_review(repo, "main", offline=True, skip_checks=True,
                                                                    no_tiers=True, log=lambda *_: None), "review.json"))
                r1 = run()
                self.assertEqual(r1["status"], "done", r1.get("reason"))
                self.assertEqual(len(r1["findings"]), 2)
                # round 2: the test lands; guard.py is untouched
                w("tests/test_ü.py", "# tests\ndef test_salvaged_guard(): assert not ok({'salvaged': True})\n")
                g("commit", "-qam", "test the guard"); verify_prompts.clear()
                r2 = run()
                self.assertEqual(r2["status"], "done", r2.get("reason"))
                self.assertEqual([f["title"] for f in r2["findings"]], ["ok() is a vague name"])
                gone = [f for f in r2["dropped"] if f["title"] == "No test for the salvaged guard"]
                self.assertEqual(len(gone), 1)
                self.assertEqual(gone[0]["anchor_changed"], ["tests/test_ü.py"])
                self.assertEqual(len(verify_prompts), 1)            # only the absence finding; the naming one carried
                self.assertEqual((r2["incremental"]["carried"], r2["incremental"]["reverified"]), (1, 1))
                self.assertEqual(r2["summary"], "only the test file changed")   # not round 1's "untested"
                # round 3: a change outside the anchor: nothing to re-verify, the naming finding still carries
                w("README.md", "docs\n"); g("add", "-A"); g("commit", "-qm", "docs"); verify_prompts.clear()
                r3 = run()
                self.assertEqual([f["title"] for f in r3["findings"]], ["ok() is a vague name"])
                self.assertEqual(verify_prompts, [])
                self.assertNotIn("untested", r3["summary"])
                g("commit", "-q", "--allow-empty", "-m", "empty")       # nothing to review: say so, don't go blank
                self.assertIn("No code changed since", run()["summary"])
                w("boom.py", "BOOM = 1\n"); g("add", "-A"); g("commit", "-qm", "boom")   # code changed, its pass failed
                r5 = run()
                self.assertEqual(r5["summary"],
                         "The review pass failed for boom.py (model call failed), so this review is incomplete; a plain re-run retries it.")
                self.assertFalse(r5["coverage"]["complete"])


class TestEvalFixtureJunk(unittest.TestCase):
    def test_build_repo_skips_pycache(self):
        # a local pytest run left base/tests/__pycache__/*.pyc in an eval fixture; the case crashed reading it as text
        from crucible import evalrun as E
        with tempfile.TemporaryDirectory() as d:
            case = os.path.join(d, "case")
            for side in ("base", "change"):
                os.makedirs(os.path.join(case, side, "tests", "__pycache__"))
                open(os.path.join(case, side, "a.py"), "w").write(f"x = '{side}'\n")
                open(os.path.join(case, side, "tests", "__pycache__", "t.cpython-314.pyc"), "wb").write(b"\x00\xb4\xff")
                open(os.path.join(case, side, "stray.pyc"), "wb").write(b"\xb4")
            out = os.path.join(d, "out"); os.makedirs(out)
            repo = E.build_repo(case, {"message": "m"}, out)        # _git sets its own identity and config
            self.assertEqual(E._git_ls(repo), ["a.py"])


class TestVerifyFailedRetried(unittest.TestCase):
    """A finding left unverified because its verifier call failed (supavisor #1142 review2 hit the 5-hour limit) is
    re-verified by a plain re-run of the same commit and on the next commit, instead of staying unverified for good.
    A transcribed "does not hold" was an answer, so it is neither retried nor re-verified just for being unverified."""

    def test_stale_inputs_and_split_prev(self):
        inp = {"base": "b1", "draft": None, "draft_sha": None}
        failed = {"severity": "low", "file": "a.js", "line": 1, "title": "t", "source": "review",
                  "verification": {"status": "unverified", "reason": "model call failed (success): You've hit your 5-hour limit"}}
        salvaged = dict(failed, verification={"status": "unverified", "reason": "its prose says no", "tiers": [{"model": "m"}]})
        done = {"status": "done", "inputs": dict(inp)}
        self.assertIn("1 finding(s) weren't verified (model call failed (success): You've hit your 5-hour limit)",
                      V.stale_inputs(dict(done, findings=[failed, salvaged]), inp))
        self.assertIsNone(V.stale_inputs(dict(done, findings=[salvaged]), inp))
        carried, touched = V.split_prev([failed, salvaged], {}, {}, "f" * 40)
        self.assertEqual([f["verification"].get("tiers") for f in touched], [None])
        self.assertEqual(len(carried), 1)
        self.assertEqual(carried[0]["verification"]["reason"], "its prose says no")
        spent = dict(failed, verification=dict(failed["verification"], attempts=V.VERIFY_ATTEMPTS))
        self.assertIsNone(V.stale_inputs(dict(done, findings=[spent]), inp))      # gave up: reused as is
        self.assertEqual([len(x) for x in V.split_prev([spent], {}, {}, "f" * 40)], [1, 0])

    def test_recurring_failure_stops_after_the_cap(self):
        repo = make_repo({"a.js": "export const a = 1;\n"}, {"a.js": "export const a = 1;\nexport const f = (xs) => xs[xs.length];\n"})
        verifies = []

        def fake(prompt, model, schema, cwd, *a, **kw):
            if "findings" in schema["properties"]:
                return {"summary": "s", "findings": [{"severity": "low", "file": "a.js", "line": 2, "title": "f reads past the end",
                        "problem": "p", "caused_by_this_change": True, "reachable_in_real_use": True, "wrong_if": "w",
                        "fix": "x"}]}, 0.01
            verifies.append(1)
            raise U.Failed("model call failed (error_max_structured_output_retries): None")
        home = tempfile.mkdtemp(prefix="crucible-home-")
        olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
        V.HOME = U.HOME = home
        os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
        V.claude = fake
        try:
            for _ in range(V.VERIFY_ATTEMPTS + 2):
                d = V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, log=lambda *_: None)
            self.assertEqual(len(verifies), V.VERIFY_ATTEMPTS)    # then reused, not paid for again
            r = U.read_json(os.path.join(d, "review.json"))
            self.assertEqual(r["findings"][0]["verification"]["attempts"], V.VERIFY_ATTEMPTS)
            self.assertIn("1 failed 3+ times and won't be retried by a plain re-run (--force does)", r["summary"])
            V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, force=True, log=lambda *_: None)
            self.assertEqual(len(verifies), V.VERIFY_ATTEMPTS + 1)
            # a later commit elsewhere: the capped finding is carried with no call, the tiered re-check included
            open(os.path.join(repo, "b.js"), "w").write("export const b = 1;\n")
            sh(repo, "git", "add", "b.js"); sh(repo, "git", "commit", "-qm", "add b")
            n = len(verifies)
            d = V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None)
            r = U.read_json(os.path.join(d, "review.json"))
            self.assertEqual((r["incremental"]["carried"], r["incremental"]["reverified"]), (1, 0))
            self.assertEqual(len(verifies), n)
            # a commit that changes its code is new code to judge, so the cap doesn't stop that re-verification
            open(os.path.join(repo, "a.js"), "w").write("export const a = 1;\nexport const f = (xs) => xs[xs.length + 0];\n")
            sh(repo, "git", "commit", "-qam", "edit f")
            d = V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, log=lambda *_: None)
            self.assertEqual(len(verifies), n + 1)
            r = U.read_json(os.path.join(d, "review.json"))
            self.assertEqual(r["incremental"]["reverified"], 1)
            self.assertEqual(r["findings"][0]["verification"]["attempts"], 1)   # its own budget, not the old code's
            V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, log=lambda *_: None)
            self.assertEqual(len(verifies), n + 2)                  # so a plain re-run retries it
            for _ in range(V.VERIFY_ATTEMPTS):                      # ...until that budget is spent too
                V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, log=lambda *_: None)
            self.assertEqual(len(verifies), n + V.VERIFY_ATTEMPTS)
        finally:
            V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
            if olds[3] is None:
                os.environ.pop("CRUCIBLE_CACHE", None)
            else:
                os.environ["CRUCIBLE_CACHE"] = olds[3]

    def test_rerun_and_next_commit_reverify(self):
        repo = make_repo({"a.js": "export const a = 1;\n", "b.js": "export const b = 1;\n"},
                         {"a.js": "export const a = 1;\nexport const f = (xs) => xs[xs.length];\n"})
        limited, verifies = [True], []

        def fake(prompt, model, schema, cwd, *a, **kw):
            if "findings" in schema["properties"]:
                hit = "+++ b/a.js" in prompt
                return {"summary": "s", "findings": [{"severity": "medium", "file": "a.js", "line": 2,
                        "title": "f reads past the end", "problem": "p", "caused_by_this_change": True,
                        "reachable_in_real_use": True, "wrong_if": "w", "fix": "x"}] if hit else []}, 0.01
            verifies.append(prompt)
            if limited[0]:
                raise U.Failed("model call failed (success): You've hit your 5-hour limit")
            return {"keep": True, "severity": "medium", "method": "read", "actions": "a", "evidence": "holds",
                    "confidence": "high"}, 0.01
        home = tempfile.mkdtemp(prefix="crucible-home-")
        olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
        V.HOME = U.HOME = home
        os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
        V.claude = fake
        run = lambda logs: V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, log=logs.append)
        status = lambda d: [f["verification"]["status"] for f in U.read_json(os.path.join(d, "review.json"))["findings"]]
        try:
            logs = []
            d = run(logs)
            r = U.read_json(os.path.join(d, "review.json"))
            self.assertEqual(status(d), ["unverified"])
            self.assertTrue(r["summary"].startswith("1 finding(s) couldn't be verified (model call failed (success): "
                                                    "You've hit your 5-hour limit); they are kept as unverified: a plain "
                                                    "re-run retries 1."), r["summary"])
            self.assertTrue(any("verification FAILED for 1 finding(s)" in l for l in logs), logs)
            limited[0] = False
            logs, n = [], len(verifies)
            run(logs)                                               # a plain re-run of the same commit retries it
            self.assertTrue(any("re-reviewing this commit: 1 finding(s) weren't verified" in l for l in logs), logs)
            self.assertEqual(len(verifies), n + 1)
            self.assertEqual(status(d), ["verified"])
            logs, n = [], len(verifies)
            run(logs)                                               # now settled: reused, no model call
            self.assertTrue(any("already reviewed this commit" in l for l in logs), logs)
            self.assertEqual(len(verifies), n)

            # next commit: a fresh branch whose first round fails verification, then a commit that leaves a.js alone
            # re-verifies the unverified finding instead of carrying it
            sh(repo, "git", "checkout", "-qb", "fix2", "main")       # other code, so no cached verdict answers it
            open(os.path.join(repo, "a.js"), "w").write("export const a = 1;\nexport const f = (ys) => ys[ys.length];\n")
            sh(repo, "git", "commit", "-qam", "again")
            limited[0] = True
            d1 = V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, fresh=True, log=lambda *_: None)
            self.assertEqual(status(d1), ["unverified"])
            limited[0] = False
            open(os.path.join(repo, "b.js"), "w").write("export const b = 2;\n")
            sh(repo, "git", "commit", "-qam", "touch b only")
            n = len(verifies)
            d2 = V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True, log=lambda *_: None)
            r2 = U.read_json(os.path.join(d2, "review.json"))
            self.assertEqual(r2["incremental"]["from"][:10], U.read_json(os.path.join(d1, "review.json"))["sha"][:10])
            self.assertEqual((r2["incremental"]["carried"], r2["incremental"]["reverified"]), (0, 1))
            self.assertEqual(len(verifies), n + 1)
            self.assertEqual(status(d2), ["verified"])
        finally:
            V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
            if olds[3] is None:
                os.environ.pop("CRUCIBLE_CACHE", None)
            else:
                os.environ["CRUCIBLE_CACHE"] = olds[3]


class TestNoExec(unittest.TestCase):
    """ROADMAP (independent bench, 2026-11-09): --skip-checks still let the verifier run node/pytest/python probes; in
    a sandbox that refused them, all 59 attempts were blocked. --no-exec (or CRUCIBLE_NO_EXEC=1) gives the verifier
    the read-only tool set and a prompt that doesn't ask it to run anything."""
    F = {"title": "off by one", "file": "a.js", "line": 3, "severity": "medium", "wrong_if": "x"}

    def test_read_only_tools_and_prompt(self):
        from unittest import mock
        calls = []

        def fake(prompt, model, schema, cwd, budget=None, tools=None, **kw):
            calls.append((prompt, tools))
            return {"keep": True, "severity": "medium", "confidence": "high", "method": "executed",
                    "actions": "ran node -e", "evidence": "e"}, 0
        with mock.patch.object(V, "claude", fake), mock.patch.dict(os.environ, {"CRUCIBLE_CACHE_VERIFY": "0"}):
            v, _ = V.verify_tiered(self.F, "code", ".", None, ["strong"], no_exec=True)
            V.verify_tiered(self.F, "code", ".", None, ["strong"])
        (ro_prompt, ro_tools), (prompt, tools) = calls
        self.assertEqual(ro_tools, U.TOOLS_READ)
        runners = ("node", "npm", "npx", "python", "pytest")
        self.assertFalse([t for t in ro_tools if any(r in t for r in runners)])
        self.assertEqual(tools, U.TOOLS_RUN)                       # default unchanged
        for r in ("node -e", "python3 -c", "npm test"):
            self.assertNotIn(r, ro_prompt)
            self.assertIn(r, prompt)
        self.assertIn("--no-exec", ro_prompt)
        self.assertEqual(v["method"], "read")                       # it had no runner: an "executed" claim is wrong
        # the default prompt is byte-identical to before the flag, so cached verdicts still match
        self.assertEqual(V.verify_prompt(self.F, "code"), V.verify_prompt(self.F, "code", no_exec=False))

    def test_read_only_verdict_isnt_reused_for_an_executing_run(self):
        inp = {"base": "b", "draft": None, "draft_sha": None}
        ro = {"status": "done", "inputs": dict(inp, no_exec=True)}
        self.assertEqual(V.stale_inputs(ro, inp), "its verification was read-only (--no-exec)")
        self.assertIsNone(V.stale_inputs(ro, dict(inp, no_exec=True)))
        # an executed verdict may stand in for a --no-exec run: nothing runs now either way
        self.assertIsNone(V.stale_inputs({"status": "done", "inputs": dict(inp)}, dict(inp, no_exec=True)))

    def test_review_end_to_end(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            repo, home = os.path.join(d, "r"), os.path.join(d, "home")
            os.makedirs(repo)
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                       GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env)
            open(os.path.join(repo, "a.py"), "w").write("x = 1\n")
            g("init", "-q", "-b", "main"); g("add", "-A"); g("commit", "-qm", "base"); g("checkout", "-qb", "x")
            open(os.path.join(repo, "a.py"), "w").write("x = 2\n"); g("commit", "-qam", "change")
            verify_tools = []

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                if "findings" in schema["properties"]:
                    return {"summary": "s", "findings": [
                        {"severity": "low", "file": "a.py", "line": 1, "title": "magic number", "problem": "p",
                         "caused_by_this_change": True, "reachable_in_real_use": True, "wrong_if": "w", "fix": "f"}]}, 0
                verify_tools.append(tools)
                return {"keep": True, "severity": "low", "confidence": "high", "method": "read", "actions": "a",
                        "evidence": "e"}, 0
            with mock.patch.object(V, "HOME", home), mock.patch.object(U, "HOME", home), \
                    mock.patch.object(V, "claude", fake), \
                    mock.patch.dict(os.environ, {"CRUCIBLE_CACHE": os.path.join(home, "c"), "CRUCIBLE_NO_EXEC": "1"}):
                with mock.patch.object(V.checks_mod, "run_all", side_effect=AssertionError("checks ran")):
                    rd = V.run_review(repo, "main", offline=True, no_tiers=True, log=lambda *_: None)   # implies skip
                r = U.read_json(os.path.join(rd, "review.json"))
                self.assertEqual(r["status"], "done", r.get("reason"))
                self.assertTrue(r["no_exec"])
                self.assertTrue(r["inputs"]["no_exec"])
                self.assertEqual(verify_tools, [U.TOOLS_READ])
                self.assertEqual(r["checks"]["note"], "skipped by --no-exec")
                self.assertIn("execution off (--no-exec)", V.report(r, {}))
                # round 2 executes: the read-only round isn't its incremental base, so its verdict isn't carried
                open(os.path.join(repo, "a.py"), "a").write("y = 3\n"); g("commit", "-qam", "more")
                verify_tools.clear()
                with mock.patch.dict(os.environ, {"CRUCIBLE_NO_EXEC": "0"}), \
                        mock.patch.object(V.checks_mod, "run_all", return_value={"results": []}):
                    r2 = U.read_json(os.path.join(V.run_review(repo, "main", offline=True, no_tiers=True,
                                                               log=lambda *_: None), "review.json"))
                self.assertEqual(r2["status"], "done", r2.get("reason"))
                self.assertNotIn("incremental", r2)
                self.assertNotIn("no_exec", r2)
                self.assertEqual(verify_tools, [U.TOOLS_RUN])
                # round 3 is read-only again: an executed round may be its base (nothing runs now either way)
                open(os.path.join(repo, "a.py"), "a").write("z = 4\n"); g("commit", "-qam", "again")
                verify_tools.clear()
                r3 = U.read_json(os.path.join(V.run_review(repo, "main", offline=True, no_tiers=True,
                                                           log=lambda *_: None), "review.json"))
                self.assertEqual(r3["status"], "done", r3.get("reason"))
                self.assertTrue(r3["no_exec"])
                self.assertEqual(r3["incremental"]["from"], r2["sha"])
                self.assertEqual(r3["incremental"]["reverified"], 1)        # the touched finding, read-only
                self.assertEqual(verify_tools, [U.TOOLS_READ])
                # round 4: a read-only round may build on a read-only one (CRUCIBLE_NO_EXEC=1 set for good)
                open(os.path.join(repo, "a.py"), "a").write("w = 5\n"); g("commit", "-qam", "once more")
                verify_tools.clear()
                r4 = U.read_json(os.path.join(V.run_review(repo, "main", offline=True, no_tiers=True,
                                                           log=lambda *_: None), "review.json"))
                self.assertEqual(r4["status"], "done", r4.get("reason"))
                self.assertEqual(r4["incremental"]["from"], r3["sha"])
                self.assertEqual(verify_tools, [U.TOOLS_READ])

    def test_cli_flag_reaches_run_review(self):
        from unittest import mock
        from crucible import cli
        seen = []
        with mock.patch("crucible.review.run_review", lambda *a, **kw: seen.append(kw["no_exec"])), \
                mock.patch.object(cli, "cmd_status", lambda a: 0):
            cli.main(["review", ".", "--no-exec"]); cli.main(["review", "."])
        self.assertEqual(seen, [True, False])


class TestRerunSameCommit(unittest.TestCase):
    """Real-use bug i: a rerun on the same commit reused the verdict even when the untracked PR_DRAFT.md (or the
    base) had changed, and --fresh without --force did too. The verdict is reused only for identical inputs."""

    def test_stale_inputs(self):
        inp = {"base": "b1", "draft": "/r/PR_DRAFT.md", "draft_sha": "h1"}
        done = {"status": "done", "inputs": dict(inp)}
        self.assertIsNone(V.stale_inputs(done, inp))
        self.assertEqual(V.stale_inputs(None, inp), "")
        self.assertEqual(V.stale_inputs(dict(done, status="failed"), inp), "")
        self.assertEqual(V.stale_inputs(done, dict(inp, draft_sha="h2")), "the draft changed since its last review")
        self.assertEqual(V.stale_inputs(done, dict(inp, base="b2")), "the base changed since its last review")
        self.assertIn("didn't record", V.stale_inputs({"status": "done"}, inp))   # written before inputs existed
        # DRG-11 o: a pass that hit a usage limit was cached, and the next run said "already reviewed this commit"
        limit = dict(done, coverage={"complete": False, "chunks": [
            {"files": ["a.js"], "status": "failed", "reason": "model call failed: Claude usage limit reached"}]})
        self.assertIn("usage limit reached", V.stale_inputs(limit, inp))
        too_big = dict(done, coverage={"complete": False, "chunks": [{"files": ["a.js"], "status": "reviewed"}]})
        self.assertIsNone(V.stale_inputs(too_big, inp))                            # nothing a re-run would change
        bare = dict(done, coverage={"chunks": [{"files": ["a.js"], "status": "failed", "reason": ""}]})
        self.assertEqual(V.stale_inputs(bare, inp), "its review pass failed (no reason recorded)")

    def test_one_failed_chunk_of_two(self):
        # the failure leads the summary, the good chunk's summary follows, and a re-run redoes only the failed chunk
        repo = make_repo({"a.js": "export const a = 1;\n", "b.js": "export const b = 1;\n"},
                         {"a.js": "export const a = 2;\n", "b.js": "export const b = 2;\n"})
        calls = []

        def fake(prompt, model, schema, cwd, *a, **kw):
            if "findings" in schema["properties"]:
                calls.append("b.js" if "+++ b/b.js" in prompt else "a.js")
                if calls[-1] == "b.js" and len(calls) < 3:
                    raise U.Failed("model call failed: usage limit")
                return {"summary": "a looks fine", "findings": []}, 0.01
            return {"keep": True, "severity": "low", "method": "read", "actions": "", "evidence": "", "confidence": "high"}, 0
        home = tempfile.mkdtemp(prefix="crucible-home-")
        olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"), V.diff_mod.chunk)
        V.HOME = U.HOME = home
        os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
        V.claude = fake
        V.diff_mod.chunk = lambda files, max_chars=45000: olds[4](files, max_chars=150)  # one chunk per file
        try:
            d = V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None)
            r = U.read_json(os.path.join(d, "review.json"))
            self.assertEqual(sorted(calls), ["a.js", "b.js"])
            self.assertTrue(r["summary"].startswith("The review pass failed for b.js (model call failed: usage limit)"), r)
            self.assertTrue(r["summary"].endswith("a looks fine"), r["summary"])
            V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None)
            self.assertEqual(calls[2:], ["b.js"])                   # a.js's pass came from the cache
            self.assertTrue(U.read_json(os.path.join(d, "review.json"))["coverage"]["complete"])
        finally:
            V.HOME, U.HOME, V.claude, V.diff_mod.chunk = olds[0], olds[1], olds[2], olds[4]
            if olds[3] is None:
                os.environ.pop("CRUCIBLE_CACHE", None)
            else:
                os.environ["CRUCIBLE_CACHE"] = olds[3]

    def test_notes_only_edit_keeps_the_hash(self):
        repo = make_repo({"a.js": "x\n"})
        p = os.path.join(repo, "PR_DRAFT.md")
        open(p, "w").write("Body.\n\n<!-- crucible: notes -->\nmine\n")
        h1 = V.review_inputs(repo, "b")["draft_sha"]
        open(p, "w").write("Body.\n\n<!-- crucible: notes -->\nmine, edited\n")
        self.assertEqual(V.review_inputs(repo, "b")["draft_sha"], h1)
        open(p, "w").write("Body, edited.\n\n<!-- crucible: notes -->\nmine, edited\n")
        self.assertNotEqual(V.review_inputs(repo, "b")["draft_sha"], h1)

    def test_unreadable_draft_is_a_clean_failure(self):
        repo = make_repo({"a.js": "x\n"})
        with self.assertRaises(U.Failed):
            V.review_inputs(repo, "b", draft=repo)                   # a directory: open() raises IsADirectoryError

    def test_draft_edit_and_fresh_rereview(self):
        repo = make_repo({"a.js": "export const a = 1;\n"}, {"a.js": "export const a = 2;\n"})
        home = tempfile.mkdtemp(prefix="crucible-home-")
        seen = []

        def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
            if "findings" in schema["properties"]:
                seen.append(prompt)
                return {"summary": "s", "findings": []}, 0.01
            return {"keep": True, "severity": "low", "method": "read", "actions": "", "evidence": "", "confidence": "high"}, 0
        draft = os.path.join(repo, "PR_DRAFT.md")
        olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
        V.HOME = U.HOME = home
        os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
        V.claude = fake
        run = lambda **kw: V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None, **kw)
        try:
            open(draft, "w").write("Bumps a to 2.\n")
            d = run()
            self.assertEqual(U.read_json(os.path.join(d, "review.json"))["status"], "done")
            self.assertEqual(len(seen), 1)
            run()                                                   # same inputs: the verdict is reused, no model call
            self.assertEqual(len(seen), 1)
            open(draft, "w").write("Bumps a to 2 because the spec says so.\n")
            run()                                                   # same commit, edited draft: judged again
            self.assertEqual(len(seen), 2)
            self.assertIn("because the spec says so", seen[-1])
            r = U.read_json(os.path.join(d, "review.json"))
            self.assertEqual(r["inputs"]["draft_sha"], V.review_inputs(repo, r["base"])["draft_sha"])
            run(fresh=True)                                         # --fresh alone redoes it and skips the cache
            self.assertEqual(len(seen), 3)
            rp = os.path.join(d, "review.json")
            r = U.read_json(rp); r.pop("inputs"); U.write_json(rp, r)
            run()                                                   # a review from before inputs were recorded: redone
            self.assertEqual(U.read_json(rp)["status"], "done")
            self.assertIn("inputs", U.read_json(rp))
            r = U.read_json(rp); r["status"] = "failed"; U.write_json(rp, r)
            n = len(seen)
            run()                                                   # a failed review is retried, not reused
            self.assertEqual(U.read_json(rp)["status"], "done")
            self.assertEqual(len(seen), n)                          # ...from the cache, so no new model call
            limited = [True]

            def limit(prompt, model, schema, cwd, *a, **kw):
                if "findings" in schema["properties"] and limited[0]:
                    raise U.Failed("model call failed: Claude usage limit reached, resets 5am")
                return fake(prompt, model, schema, cwd, *a, **kw)
            V.claude = limit
            logs = []
            V.run_review(repo, "main", offline=True, skip_checks=True, fresh=True, log=logs.append)  # hits the limit
            self.assertTrue(any("review pass FAILED for 1 file(s): model call failed: Claude usage" in l for l in logs), logs)
            r = U.read_json(rp)
            self.assertFalse(r["coverage"]["complete"], r)
            self.assertIn("usage limit reached", r["summary"])      # the reason is shown, not just "incomplete"
            limited[0] = False
            logs = []
            V.run_review(repo, "main", offline=True, skip_checks=True, log=logs.append)   # a plain re-run retries it
            self.assertTrue(any("re-reviewing this commit: its review pass failed" in l for l in logs), logs)
            self.assertTrue(U.read_json(rp)["coverage"]["complete"])
        finally:
            V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
            if olds[3] is None:
                os.environ.pop("CRUCIBLE_CACHE", None)
            else:
                os.environ["CRUCIBLE_CACHE"] = olds[3]



class TestUntrackedScratchFiles(unittest.TestCase):
    """Bug h (Heroic): a lint that globs the working tree crashed on an untracked scratch .cjs in the repo root,
    and the PR was reported as failing lint. Bug f: the base worktree's node_modules symlink hit EEXIST."""

    LINT = ("import os, sys\n"
            "bad = [p for p in sorted(os.listdir('.')) if p.endswith('.cjs') and 'BROKEN' in open(p).read()]\n"
            "print('\\n'.join(f'{p}: Parsing error' for p in bad)); sys.exit(1 if bad else 0)\n")

    def _repo(self, extra=None):
        from crucible import checks as C  # noqa: F401
        d = make_repo({"lint.py": self.LINT, "a.cjs": "ok\n", **(extra or {})}, {"a.cjs": "ok, changed\n"})
        os.makedirs(os.path.join(_TMP_HOME, "projects", "x"), exist_ok=True)
        open(os.path.join(_TMP_HOME, "projects", "x", "config.json"), "w").write(
            '{"checks": [{"name": "lint", "cmd": "%s lint.py"}]}' % sys.executable)
        return d

    def test_failure_on_untracked_file_is_rejudged_on_a_clean_checkout(self):
        from crucible import checks as C
        d = self._repo()
        open(os.path.join(d, "capture.cjs"), "w").write("BROKEN\n")
        res = C.run_all(d, "x", log=lambda *a: None)["results"][0]
        self.assertEqual(res["status"], "pass")
        self.assertEqual(res["untracked"], ["capture.cjs"])
        self.assertEqual(res["in_working_tree"], "fail")
        self.assertIn("failed in the working tree only", C.facts({"results": [res]}))
        self.assertEqual(sh(d, "git", "worktree", "list").count("\n"), 0)  # the throwaway worktree is gone

    def test_a_real_failure_still_fails(self):
        from crucible import checks as C
        d = self._repo()
        open(os.path.join(d, "a.cjs"), "w").write("BROKEN\n"); sh(d, "git", "commit", "-qam", "break")
        open(os.path.join(d, "capture.cjs"), "w").write("BROKEN\n")
        res = C.run_all(d, "x", log=lambda *a: None)["results"][0]
        self.assertEqual(res["status"], "fail")
        self.assertIn("a.cjs: Parsing error", res["tail"])
        self.assertNotIn("capture.cjs", res["tail"])  # the clean run's output replaces the working-tree one
        self.assertIn("capture.cjs", res["working_tree_tail"])
        fx = C.facts({"results": [res]})
        self.assertIn("on a clean checkout of HEAD", fx)
        # both outputs: the working-tree tail first, then the clean checkout's
        self.assertLess(fx.index("capture.cjs: Parsing error"), fx.index("Clean checkout"))
        self.assertIn("a.cjs: Parsing error", fx[fx.index("Clean checkout"):])

    def test_failure_not_naming_untracked_files_is_not_rerun(self):
        from crucible import checks as C
        d = self._repo()
        open(os.path.join(d, "a.cjs"), "w").write("BROKEN\n"); sh(d, "git", "commit", "-qam", "break")
        open(os.path.join(d, "notes.txt"), "w").write("scratch\n")
        res = C.run_all(d, "x", log=lambda *a: None)["results"][0]
        self.assertEqual(res["status"], "fail")
        self.assertNotIn("untracked", res)

    def test_mentioned_matches_whole_paths_only(self):
        from crucible import checks as C
        out = "src/a.cjs: error\nfoo.cjs.map ok\n"
        self.assertEqual(C.mentioned(out, ["src/a.cjs", "a.cjs", "foo.cjs", "b.cjs"]), ["src/a.cjs"])
        self.assertEqual(C.mentioned("/r/cap.cjs\n  1:1 error", ["cap.cjs"], "/r"), ["cap.cjs"])  # eslint: absolute
        self.assertEqual(C.mentioned("x.cjs: error", ["pk/x.cjs"], "/r", "pk"), ["pk/x.cjs"])  # relative to cwd
        self.assertEqual(C.mentioned("/other/cap.cjs", ["cap.cjs"], "/r"), [])
        self.assertEqual(C.mentioned("./cap.cjs: SyntaxError", ["cap.cjs"], "/r"), ["cap.cjs"])
        self.assertEqual(C.mentioned("at file:///r/cap.mjs:3:1", ["cap.mjs"], "/r"), ["cap.mjs"])
        self.assertEqual(C.mentioned("see cap.cjs.", ["cap.cjs"]), ["cap.cjs"])  # end of a sentence
        self.assertEqual(C.mentioned("/r/my scratch.js: error", ["my scratch.js"], "/r"), ["my scratch.js"])
        self.assertEqual(C.mentioned("app/[id]/page.tsx:1 x", ["app/[id]/page.tsx", "[id]/page.tsx"]), ["app/[id]/page.tsx"])
        self.assertEqual(C.mentioned("./my scratch.js: e", ["my scratch.js"], "/r"), ["my scratch.js"])
        self.assertEqual(C.mentioned("at file:///r/my scratch.js:3", ["my scratch.js"], "/r"), ["my scratch.js"])
        self.assertEqual(C.mentioned("/my repo/pk/x.js:1", ["pk/x.js"], "/my repo", "pk"), ["pk/x.js"])
        self.assertEqual(C.mentioned("/other/r/cap.cjs", ["cap.cjs"], "/r"), [])  # another tree's /r/
        for out in ("/other/./cap.cjs", "../cap.cjs", "/r2/cap.cjs", "src/./cap.cjs"):
            self.assertEqual(C.mentioned(out, ["cap.cjs"], "/r"), [], out)
        self.assertEqual(C.mentioned("/r/./cap.cjs: e", ["cap.cjs"], "/r"), ["cap.cjs"])

    def test_mentioned_is_linear(self):
        import time
        from crucible import checks as C
        paths = [f"scratch/f{i}.js" for i in range(20000)]
        out = "\n".join(f"src/mod{i}.ts:1:1 error" for i in range(50000))
        for repo in ("/r", "/home/u/My Projects/app"):  # a space in the repo path must not force a scan per file
            t = time.monotonic()
            self.assertEqual(C.mentioned(out + f"\n{repo}/scratch/f7.js: x", paths, repo), ["scratch/f7.js"])
            self.assertLess(time.monotonic() - t, 2)

    def test_f_existing_node_modules_in_the_worktree_is_left_alone(self):
        from crucible import checks as C
        d = self._repo({"node_modules/.keep": ""})
        os.makedirs(os.path.join(d, "node_modules", "pkg"))  # installed deps (untracked inside a tracked dir)
        res = C.run_in_worktree(d, "HEAD", {"cmd": "test -f node_modules/.keep && test ! -L node_modules"})
        self.assertEqual(res["status"], "pass")


class TestDescriptionHeuristics(unittest.TestCase):
    """Real-use bugs g (Heroic: the template's comment, checklist and title counted as body length) and
    m (three.js: "Checked with `npm run build-docs`" was not accepted as testing evidence)."""
    TPL = ("<!--\n    Describe your PR below this comment\n    AI disclosure: say how AI was used, if it was, in a few"
           " words and examples of what to write here\n-->\n\n---\n\nUse the following Checklist if you have"
           " changed something on the Backend or Frontend:\n\n"
           "- [ ] Tested the feature and it's working on a current and clean install.\n"
           "- [ ] Tested the main App features and they are still working on a current and clean install.\n"
           "- [ ] Created / Updated Tests (If necessary)\n- [ ] Created / Updated documentation (If necessary)\n")
    STYLE = {"body": {"median_words": 40, "pct_with_emoji": 0, "pct_with_headings": 100, "common_headings": []}}
    TITLE = "fix: Sort the library the same way in desktop and console mode"

    def draft(self, prose_words):
        filled = self.TPL.replace("- [ ] Tested the feature", "- [x] Tested the feature")
        body = filled.replace("-->\n", "-->\n\nCloses #5967\n\n" + "word " * prose_words + "\n", 1)
        return self.TITLE + "\n\n" + body

    def test_g_template_comment_checklist_and_title_are_not_length(self):
        text = self.draft(100)
        self.assertGreater(S.words(text), 190)  # what used to be measured: > max(2.5*40, 40+150)
        self.assertEqual(S.body_words(text, self.TPL, self.TITLE), 102)  # "Closes #5967" + the prose
        self.assertNotIn("length", {k for k, _ in S.ai_tells(text, self.STYLE, (), self.TPL, self.TITLE)})

    def test_g_long_prose_is_still_flagged(self):
        text = self.draft(200)
        self.assertIn("length", {k for k, _ in S.ai_tells(text, self.STYLE, (), self.TPL, self.TITLE)})

    def test_g_edited_template_line_counts(self):
        # a checklist line the author rewrote is their own text, not the template's
        text = self.TITLE + "\n\n- [x] Tested the feature on a clean Flatpak install and on the AppImage\n"
        self.assertEqual(S.body_words(text, self.TPL, self.TITLE), 13)

    def test_g_check_reads_the_repo_template(self):
        d = make_repo({".github/pull_request_template.md": self.TPL})
        text = self.draft(120) + "\nTested in the running app.\n"
        self.assertEqual(S.check(d, "HEAD", [], "PR_DRAFT.md", text, self.STYLE, title=self.TITLE), [])
        # without the template the checklist and comment count again, and the draft reads as too long
        self.assertIn("PR description: length reads as generated",
                      [f["title"] for f in S.check(make_repo({"a.txt": "x"}), "HEAD", [], "PR_DRAFT.md", text, self.STYLE)])

    def test_outside_baseline_replays_real_reviews(self):
        """Stored upstream length findings, replayed on the outside-contributor medians measured 2026-11-06."""
        def tells(w, med, outside):
            return {k for k, _ in S.ai_tells("word " * w, {"body": {"median_words": med, "outside_median_words": outside,
                                                                    "outside_prs": 14}})}
        self.assertNotIn("length", tells(183, 17, 144))  # three-mesh-bvh, was flagged medium
        self.assertNotIn("length", tells(182, 26, 54))   # MangoHud, was flagged
        self.assertIn("length", tells(327, 19, 20))      # colyseus: its outside contributors are terse too
        self.assertIn("length", tells(1258, 74, 182))    # three.js: still far too long
        self.assertNotIn("length", tells(300, 0, 0))     # an empty-bodied project gives no baseline, as before

    def test_m_backticked_build_or_test_command_is_evidence(self):
        for line in ("No code changes. Checked with `npm run build-docs`: both entries show up.",
                     "Ran `cargo test -p core` locally: 212 passed.",
                     "`python3 -m unittest` passes.",
                     "Reproduced on 5.0.44 and confirmed fixed.",
                     "Screenshots attached.",  # prefixes match, as before the change
                     "`npm run build-docs` shows both entries.",  # only the command branch matches these two
                     "`$ make check` is green here.",
                     "Built with `cd docs && make html`.", "`CI=1 npm run lint` is clean.",  # chained / env prefix
                     "`make build; make test` is green.", "`cat out.json | python3 -m json.tool` parses.",
                     "`false || cargo build --release` works.", "`sudo make install` works."):
            self.assertTrue(S.has_testing_evidence(line), line)
        # file and tool names, prose between two spans, and spans whose parts aren't commands
        for line in ("Bumps `yarn.lock` for the new dep.", "Updated `Cargo.toml` to pick up the new dep.",
                     "Adds a `python` binding for the parser.", "The `parse()` helper drops a token.",
                     "Moved `a` go through `b`.", "`int | None` is accepted.", "`a || b` short-circuits."):
            self.assertFalse(S.has_testing_evidence(line), line)

    def test_m_no_evidence_is_still_flagged(self):
        d = make_repo({"a.txt": "x"})
        text = "Fixes #12.\n\nThe `parse()` helper dropped the last `token` of a line, so use `split()` instead."
        titles = [f["title"] for f in S.check(d, "HEAD", [], "PR_DRAFT.md", text, {})]
        self.assertIn("PR description: no testing evidence", titles)


class TestRouting(unittest.TestCase):
    """Cost routing by change type and the offline replay that gates each rule."""

    def test_change_kind(self):
        for paths in (["README.md"], ["docs/guide.rst", "CHANGELOG"], ["packages/x/README.md", "LICENSE"], ["README.txt", "docs/api.adoc"],
                      ["docs/guides/getting-started.md"], ["docs/user-guide/index.md"], ["doc/prompt-engineering.rst"],
                      ["docs/prompts/system.md"]):   # inside a docs tree, prompt-named prose is documentation
            self.assertEqual(RT.change_kind(paths), "docs", paths)
        # falsifiers: any code file makes it code; nothing changed is not "docs"; docs-looking names that aren't
        for paths in (["README.md", "src/a.js"], [], ["src/docstring.py"], ["docs.js"], ["src/readme_parser.py"],
                      ["assets/logo.png"], ["requirements.txt"], ["CMakeLists.txt"], ["docs/conf.py"],
                      ["docs/examples/demo.py"], ["CLAUDE.md"], ["sub/AGENTS.md"], ["crucible/guides/answering.md"],
                      ["prompts/review.md"], [".github/copilot-instructions.md"], ["improve-prompt.md"],
                      ["SYSTEM_PROMPT.md"], [".claude/skills/x/SKILL.md"], [".claude/commands/x.md"],
                      ["system_prompts/review.md"], ["prompt_templates/a.md"], [".github/instructions/py.md"],
                      ["userguide/x.md"], ["docs/CLAUDE.md"], ["docs/.claude/commands/x.md"],
                      # deliberately conservative: a substring match on the directory errs toward the full pass
                      ["prompt_toolkit/README.md"], ["guidelines/CONTRIBUTING.md"]):
            self.assertEqual(RT.change_kind(paths), "code", paths)

    def test_enabled(self):
        old = os.environ.get("CRUCIBLE_ROUTE")
        try:
            for val, want in (("1", True), ("true", True), ("YES", True), ("", False), ("0", False), ("false", False),
                              ("off", False), ("no", False)):
                os.environ["CRUCIBLE_ROUTE"] = val
                self.assertEqual(RT.enabled(None), want, val)
            os.environ["CRUCIBLE_ROUTE"] = "1"
            self.assertFalse(RT.enabled(False))                   # an explicit argument wins
            os.environ.pop("CRUCIBLE_ROUTE")
            self.assertFalse(RT.enabled(None))
            self.assertTrue(RT.enabled(True))
        finally:
            if old is None:
                os.environ.pop("CRUCIBLE_ROUTE", None)
            else:
                os.environ["CRUCIBLE_ROUTE"] = old

    def test_route(self):
        tiers = ["claude-haiku-5-5", "claude-sonnet-5-5"]
        self.assertEqual(RT.route("code", "claude-opus-5-5", tiers), ("claude-opus-5-5", tiers))
        self.assertEqual(RT.route("docs", "claude-opus-5-5", tiers), ("claude-sonnet-5-5", tiers[:1]))
        # the mid model wrote the change: keep the independent reviewer, still one verification tier
        self.assertEqual(RT.route("docs", "claude-opus-5-5", tiers, ["claude-sonnet-5-5"]),
                         ("claude-opus-5-5", tiers[:1]))

    @staticmethod
    def _store(root, repo, sha, started, findings=(), dropped=(), files=("src/a.js",), answers=None, **extra):
        d = os.path.join(root, repo, sha)
        os.makedirs(d)
        U.write_json(os.path.join(d, "review.json"), dict(
            {"repo": repo, "sha": sha, "base": "b0", "status": "done", "started": started, "inputs": {"draft": "D"},
             "coverage": {"chunks": [{"files": list(files)}]}, "cost_usd": 1.0, "cost_review_usd": 0.7,
             "cost_verify_usd": 0.3, "findings": list(findings), "dropped": list(dropped)}, **extra))
        if answers:
            U.write_json(os.path.join(d, "answers.json"), answers)

    @staticmethod
    def _f(fid, sev, title, cheap, strong=None, **kw):
        tiers = [dict(model="haiku", **cheap)] + ([dict(model="sonnet", **strong)] if strong else [])
        return dict({"id": fid, "source": "review", "severity": sev, "title": title, "file": "src/a.js",
                     "verification": {"tiers": tiers}}, **kw)

    def test_replay_counts_losses_once_at_their_worst(self):
        with tempfile.TemporaryDirectory() as root:
            low_lost = self._f("CR-1", "low", "ruff claim is false", {"keep": False, "severity": "low"},
                               {"keep": True, "severity": "low"})
            med_down = self._f("CR-2", "medium", "cost grows", {"keep": True, "severity": "low"},
                               {"keep": True, "severity": "medium"})
            med_lost = self._f("CR-2", "medium", "cost grows", {"keep": False, "severity": "low"},
                               {"keep": True, "severity": "medium"})
            extra = self._f("CR-3", "low", "noise", {"keep": True, "severity": "low"}, {"keep": False, "severity": "low"})
            not_low = self._f("CR-4", "important", "proposed important", {"keep": True, "severity": "low"},
                              {"keep": False, "severity": "low"})        # dropped: its proposal is known, not low
            settled = self._f("CR-5", "low", "cheap tier was sure", {"keep": True, "severity": "low"})
            self._store(root, "o__p", "s1", "2026-11-05T01", [low_lost, med_down, settled], [extra, not_low])
            self._store(root, "o__p", "s2", "2026-11-05T02", [med_lost], answers={"CR-2": {"disposition": "fixed"}})
            self._store(root, "o__p", "s3", "2026-11-05T03", files=["README.md"])
            self._store(root, "o__p", "s5", "2026-11-05T05", cost_usd=0.25,     # an amend re-reviewed incrementally
                        incremental={"from": "s3", "files": ["src/a.js"], "amended": True})
            self._store(root, "JROtto5__crucible", "s4", "2026-11-05T04",
                        [self._f("CR-9", "important", "self", {"keep": False, "severity": "low"},
                                 {"keep": True, "severity": "important"})])
            r = RT.replay(root)
            self.assertEqual(r["reviews"], 4)                     # crucible's own reviews are left out by default
            lc = r["low_cheap"]
            self.assertEqual(lc["decided"], 3)                    # CR-1, "cost grows" (2 sightings), CR-3
            self.assertEqual(lc["sightings"], 4)
            self.assertEqual(dict(lc["lost"]), {"low": 1, "medium": 1})   # the medium counts once, as lost
            self.assertEqual(dict(lc["downgraded"]), {})
            self.assertEqual(lc["extra_kept"], 1)
            self.assertEqual([t for _, _, t in lc["lost_fixed"]], ["cost grows"])
            self.assertFalse(RT.safe(lc["lost"], lc["downgraded"]))
            self.assertEqual((r["docs"]["reviews"], r["repeat_full"]["reviews"]), (1, 2))
            self.assertEqual(r["amend_incremental"], {"reviews": 1, "cost": 0.25})
            self.assertEqual(r["raw"], 6)
            self.assertEqual(r["dropped"], 2)
            text = RT.replay_report(r)
            self.assertIn("Fails the bar: stays off", text)
            self.assertIn("lost and later fixed by the author: [medium] cost grows", text)
            self.assertIn("Refuted share would go 33% → 50%", text)   # (2 dropped - 1 extra kept + 2 lost) of 6
            self.assertIn("Amended commits re-reviewed incrementally: 1 ($0.25)", text)
            self.assertEqual(RT.replay(root, include_self=True)["low_cheap"]["lost"]["important"], 1)

    def test_replay_counts_a_carried_finding_in_the_round_that_judged_it(self):
        """11-07 exchange: the raw refuted share read 63% because each incremental round re-lists the previous round's
        dropped findings unjudged, and refuted findings ride along forever. Counted where judged it was 50%."""
        with tempfile.TemporaryDirectory() as root:
            refuted = self._f("CR-1", "low", "noise", {"keep": False, "severity": "low"}, {"keep": False, "severity": "low"})
            real = self._f("CR-2", "low", "real", {"keep": True, "severity": "low"}, {"keep": True, "severity": "low"})
            self._store(root, "o__p", "aaaaaaaaaaaa", "2026-11-05T01", [real], [refuted])
            self._store(root, "o__p", "bbbbbbbbbbbb", "2026-11-05T02", [dict(real, carried_from="aaaaaaaaaa")],
                        [dict(refuted, carried_from="aaaaaaaaaa")], incremental={"from": "aaaaaaaaaaaa"})
            # round 3: the refuted one carried again; the real one re-verified (its old carried_from is stale)
            self._store(root, "o__p", "cccccccccccc", "2026-11-05T03",
                        [dict(real, carried_from="aaaaaaaaaa", reverified_from="bbbbbbbbbb")],
                        [dict(refuted, carried_from="bbbbbbbbbb")], incremental={"from": "bbbbbbbbbbbb"})
            r = RT.replay(root)
            self.assertEqual((r["raw"], r["dropped"]), (3, 1))   # round 1: both; round 3: the re-verified one
            self.assertEqual(r["low_cheap"]["sightings"], 3)
            self.assertEqual(r["low_cheap"]["decided"], 2)
            self.assertIn("3 model findings, 1 refuted by verification (33%)", RT.replay_report(r))
            med = self._f("CR-3", "medium", "real medium", {"keep": True, "severity": "medium"})
            self._store(root, "o__q", "dddddddddddd", "2026-11-05T04", [med])
            self._store(root, "o__q", "eeeeeeeeeeee", "2026-11-05T05", [dict(med, carried_from="dddddddddd")],
                        files=["README.md"], incremental={"from": "dddddddddddd", "files": ["README.md"]})
            r = RT.replay(root)
            self.assertEqual(r["docs"]["reviews"], 1)
            self.assertEqual(dict(r["docs"]["at_risk"]), {})     # the docs round only carried the code finding
            # falsifier: a full (non-incremental) round re-judges everything, so nothing in it is a carried copy
            self.assertFalse(RT.carried_here(dict(refuted, carried_from="bbbbbbbbbb"), {"incremental": None}))

    def test_safe_bar(self):
        self.assertTrue(RT.safe({"low": 3}))
        self.assertFalse(RT.safe({"medium": 1}))
        self.assertFalse(RT.safe({}, {"medium": 1}))
        self.assertFalse(RT.safe({"important": 1}))

    def test_run_review_routes_a_docs_round(self):
        for paths, kind in ((("README.md", "docs/use.md"), "docs"), (("README.md", "src/a.py"), "code")):
            with tempfile.TemporaryDirectory() as d:
                repo, home = os.path.join(d, "r"), os.path.join(d, "home")
                env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                           GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
                g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env)
                os.makedirs(os.path.join(repo, "docs")); os.makedirs(os.path.join(repo, "src"))
                g("init", "-q", "-b", "main")
                for p in paths:
                    open(os.path.join(repo, p), "w").write("old\n")
                g("add", "-A"); g("commit", "-qm", "base"); g("checkout", "-qb", "x")
                for p in paths:
                    open(os.path.join(repo, p), "w").write("old\nnew line\n")
                g("commit", "-qam", "change")
                calls = []

                def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                    calls.append((model, "findings" in schema["properties"]))
                    if "findings" in schema["properties"]:
                        return {"summary": "s", "findings": [
                            {"severity": "low", "file": paths[0], "line": 2, "title": "unclear sentence", "problem": "p",
                             "caused_by_this_change": True, "reachable_in_real_use": True, "wrong_if": "w", "fix": "f"}]}, 0.01
                    # unsure: without routing this escalates to the strong tier
                    return {"keep": True, "severity": "low", "method": "read", "actions": "a", "evidence": "e",
                            "confidence": "medium"}, 0.001

                olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
                V.HOME = U.HOME = home
                os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
                V.claude = fake
                try:
                    r = U.read_json(os.path.join(V.run_review(repo, "main", offline=True, skip_checks=True, route=True,
                                                              author="claude-haiku-5-5", log=lambda *_: None), "review.json"))
                finally:
                    V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
                    if olds[3] is None:
                        os.environ.pop("CRUCIBLE_CACHE", None)
                    else:
                        os.environ["CRUCIBLE_CACHE"] = olds[3]
                self.assertEqual(r["status"], "done", r.get("reason"))
                self.assertEqual(r["route"]["kind"], kind)
                reviewers = [m for m, is_review in calls if is_review]
                verifiers = [m for m, is_review in calls if not is_review]
                f = r["findings"][0]
                self.assertEqual(f["proposed_severity"], "low")
                self.assertEqual(f["verification"]["tiers"][0]["cost"], 0.001)
                if kind == "docs":
                    self.assertEqual((reviewers, verifiers), (["claude-sonnet-5-5"], ["claude-haiku-5-5"]))
                    self.assertEqual(r["review_model"], "claude-sonnet-5-5")
                else:                                         # code keeps the full pipeline
                    self.assertEqual(reviewers, ["claude-opus-5-5"])
                    self.assertEqual(verifiers, ["claude-haiku-5-5", "claude-sonnet-5-5"])


    def test_routed_docs_round_still_rechecks_carried_findings(self):
        with tempfile.TemporaryDirectory() as d:
            repo, home = os.path.join(d, "r"), os.path.join(d, "home")
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                       GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env)
            w = lambda p, t: open(os.path.join(repo, p), "w").write(t)
            os.makedirs(os.path.join(repo, "src"))
            g("init", "-q", "-b", "main"); w("src/a.js", "export const a = 1;\n"); w("README.md", "# r\n")
            g("add", "-A"); g("commit", "-qm", "base"); g("checkout", "-qb", "x")
            w("src/a.js", "export const a = 1;\nexport const b = () => 2;\n"); g("commit", "-qam", "add b")
            calls = []

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                recheck = "changed since then" in prompt
                calls.append((model, "findings" in schema["properties"], recheck))
                if "findings" in schema["properties"]:
                    return {"summary": "s", "findings": [] if "src/a.js" not in prompt else [
                        {"severity": "medium", "file": "src/a.js", "line": 2, "title": "b is undocumented in the README",
                         "problem": "p", "caused_by_this_change": True, "reachable_in_real_use": True, "wrong_if": "w",
                         "fix": "f"}]}, 0.01
                return {"keep": not recheck, "severity": "medium", "method": "read", "actions": "a",
                        "evidence": "README now documents b" if recheck else "e", "confidence": "high"}, 0.001

            olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
            V.HOME = U.HOME = home
            os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
            V.claude = fake
            try:
                V.run_review(repo, "main", offline=True, skip_checks=True, route=True, log=lambda *_: None)
                w("README.md", "# r\n\n`b()` returns 2.\n"); g("commit", "-qam", "document b")   # docs-only round
                calls.clear()
                r = U.read_json(os.path.join(V.run_review(repo, "main", offline=True, skip_checks=True, route=True,
                                                          log=lambda *_: None), "review.json"))
            finally:
                V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
                if olds[3] is None:
                    os.environ.pop("CRUCIBLE_CACHE", None)
                else:
                    os.environ["CRUCIBLE_CACHE"] = olds[3]
            self.assertEqual(r["status"], "done", r.get("reason"))
            self.assertEqual(r["route"]["kind"], "docs")
            self.assertEqual(r["incremental"]["carried"], 1)
            self.assertIn(("claude-haiku-5-5", False, True), calls)            # the carried finding was re-checked
            self.assertEqual([f["title"] for f in r["dropped"]], ["b is undocumented in the README"])

class TestStats(unittest.TestCase):
    """`crucible stats`: one unique finding however many rounds showed it; latest answer wins."""
    @staticmethod
    def _store(root, repo, sha, findings=(), dropped=(), answers=None, cost=1.0):
        d = os.path.join(root, repo, sha)
        os.makedirs(d)
        U.write_json(os.path.join(d, "review.json"), {"repo": repo, "sha": sha, "status": "done", "cost_usd": cost,
                                                      "findings": list(findings), "dropped": list(dropped)})
        if answers:
            U.write_json(os.path.join(d, "answers.json"), answers)

    @staticmethod
    def _f(fid, title, sev="low", source="review"):
        return {"id": fid, "title": title, "severity": sev, "source": source, "file": "a.js", "line": 1}

    def test_dedupes_carried_ids_and_amended_rereviews(self):
        from crucible import stats as ST
        with tempfile.TemporaryDirectory() as root:
            # round 1: two findings + one dropped; a scanner finding never counts
            self._store(root, "o__p", "s1", [self._f("CR-1", "Off-by-one in loop", "medium"),
                                             self._f("CR-2", "No test for clamp"), self._f("SC-1", "TODO", source="scanner")],
                        [self._f("CR-3", "Style nit")], answers={"CR-1": {"disposition": "fixed", "at": "2026-11-05T04"}})
            # round 2 (incremental): CR-1 carried with its id; its answer here is older than round 1's, so it loses
            # (answers are re-dated when edited by hand); CR-3 now kept
            self._store(root, "o__p", "s2", [self._f("CR-1", "Off-by-one in loop", "medium"), self._f("CR-3", "Style nit")],
                        answers={"CR-1": {"disposition": "refuted", "at": "2026-11-05T02"}})
            # round 3 (amended commit, full re-review): same title, new id, title differs only in case/punctuation
            self._store(root, "o__p", "s3", [self._f("CR-9", "no test for clamp.")],
                        answers={"CR-9": {"disposition": "deferred", "at": "2026-11-05T03"}})
            # the same title in another project is a different finding; always dropped there
            self._store(root, "o__q", "t1", dropped=[self._f("CR-5", "No test for clamp")])
            self._store(root, "JROtto5__crucible", "c1", [self._f("CR-7", "self")])
            self._store(root, "o__p", "s4", [self._f("CR-8", "x")])
            self._store(root, "o__my__lib", "m1", dropped=[self._f("CR-6", "y")])   # a repo name with "__"
            os.remove(os.path.join(root, "o__p", "s4", "review.json"))     # an unfinished review dir is ignored
            s = ST.collect(root)
            o = s["overall"]
            self.assertEqual((o["unique"], o["kept"], o["dropped"]), (5, 3, 2))
            self.assertEqual((o["fixed"], o["deferred"], o["refuted"], o["unanswered"]), (1, 1, 0, 1))
            self.assertEqual(dict(o["kept_by_severity"]), {"medium": 1, "low": 2})
            self.assertEqual((o["reviews"], o["cost"]), (5, 5.0))
            self.assertEqual(sorted(s["projects"]), ["o__my__lib", "o__p", "o__q"])
            self.assertEqual(ST.held_up(o), (2, 2))
            self.assertIsNone(ST.held_up(s["projects"]["o__q"]))
            self.assertEqual(ST.collect(root, include_self=True)["overall"]["unique"], 6)
            self.assertEqual(list(ST.collect(root, project="o/q")["projects"]), ["o__q"])
            text = ST.report(s)
            self.assertIn("o/p", text)
            self.assertIn("2/2 (100%)", text)
            self.assertIn("verification kept 3 (60%) and dropped 2", text)
            self.assertIn("o/my__lib ", text)
            self.assertIn("1 of 3 kept are unanswered", text)
            self.assertEqual(json.loads(ST.to_json(s))["overall"]["kept_by_severity"], {"medium": 1, "low": 2})

    def test_cli(self):
        with tempfile.TemporaryDirectory() as home:
            self._store(os.path.join(home, "reviews"), "o__p", "s1", [self._f("CR-1", "t")])
            out = subprocess.run([sys.executable, "-m", "crucible", "stats", "--json"], capture_output=True, text=True,
                                 env=dict(os.environ, CRUCIBLE_HOME=home), cwd=os.path.dirname(os.path.dirname(__file__)))
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout)["overall"]["unique"], 1)


class TestStatsWindow(unittest.TestCase):
    """BLAZE 2 exchange 2026-11-07: a query over a store that stopped being written returns zero rows, and "0 reviews"
    reads as a quiet day. `stats --since` reports what it read and says "no data" instead of printing zeros."""
    @staticmethod
    def _store(root, sha, finished, findings=(), answers=None, cost=1.0, repo="o__p"):
        TestStats._store(root, repo, sha, findings, answers=answers, cost=cost)
        p = os.path.join(root, repo, sha, "review.json")
        rev = U.read_json(p)
        rev.update(finished or {})
        U.write_json(p, rev)

    def test_window_counts_only_rounds_in_it_and_keeps_older_answers(self):
        from crucible import stats as ST
        f = TestStats._f
        with tempfile.TemporaryDirectory() as root:
            # CR-1 raised and answered before the window, carried into it: it counts, with its old answer
            self._store(root, "s1", {"finished": "2026-11-06T10:00:00"}, [f("CR-1", "a")],
                        answers={"CR-1": {"disposition": "fixed", "at": "2026-11-06T11"}})
            self._store(root, "s2", {"finished": "2026-11-07T06:00:00"}, [f("CR-1", "a"), f("CR-2", "b")], cost=2.0)
            self._store(root, "s3", {"started": "2026-11-07T09:00:00"}, [f("CR-3", "c")], cost=0.5)  # no "finished"
            self._store(root, "s0", None, [f("CR-0", "z")])                                         # legacy, undated
            s = ST.collect(root, since="2026-11-07T05:15:00")
            o, w = s["overall"], s["window"]
            self.assertEqual((o["reviews"], o["cost"], o["unique"], o["fixed"], o["unanswered"]), (2, 2.5, 3, 1, 2))
            self.assertEqual(w, {"since": "2026-11-07T05:15:00", "project": None, "stored": 4, "undated": 1,
                                 "newest": "2026-11-07T09:00:00", "in_window": 2})
            self.assertEqual(ST.collect(root)["overall"]["reviews"], 4)                  # no window: everything
            text = ST.report(s)
            self.assertIn("Window: reviews finished since 2026-11-07 05:15:00: 2 of 4.", text)
            self.assertIn("Read 4 finished reviews, 1 undated; the newest is from 2026-11-07 09:00.", text)
            self.assertIn("Held up: 1/1 = 100% (Wilson 95% 21%-100%; n=1 < 60, too few to quote", text)
            self.assertIn("Cost per held-up finding: $2.50", text)
            j = json.loads(ST.to_json(s))
            self.assertTrue(j["answered"])
            self.assertEqual((j["held_up"]["held"], j["held_up"]["answered"], j["held_up"]["quotable"]), (1, 1, False))

    def test_empty_window_is_no_data_not_zero(self):
        from crucible import stats as ST
        with tempfile.TemporaryDirectory() as root:
            self._store(root, "s1", {"finished": "2026-11-06T10:00:00"}, [TestStats._f("CR-1", "a")])
            s = ST.collect(root, since="2026-11-08")
            text = ST.report(s)
            self.assertTrue(text.startswith("No data: no finished review since 2026-11-08."), text)
            self.assertIn("the newest is from 2026-11-06 10:00", text)
            self.assertNotIn("overall", text)                         # no table of zeros
            j = json.loads(ST.to_json(s))
            self.assertEqual((j["answered"], j["overall"], j["window"]["in_window"]), (False, None, 0))
            # an empty store says so too
            self.assertIn("newest is from never", ST.report(ST.collect(os.path.join(root, "none"))))
            # a --project that matches nothing names the project, not the whole store
            text = ST.report(ST.collect(root, project="o/typo"))
            self.assertTrue(text.startswith("No data: no finished review of o/typo stored. Read 0 finished reviews of o/typo;"), text)
            self.assertIn("nothing here was reviewed", text)
            self.assertIn("Read 1 finished review of o/p; the newest", ST.report(ST.collect(root, project="o/p")))

    def test_quote_bar_boundary(self):
        from crucible import stats as ST
        with tempfile.TemporaryDirectory() as root:
            for i in range(60):
                self._store(root, f"s{i}", {"finished": "2026-11-07T06:00:00"}, [TestStats._f(f"CR-{i}", f"t{i}")],
                            answers={f"CR-{i}": {"disposition": "fixed" if i % 5 else "refuted", "at": "x"}})
            s = ST.collect(root)
            self.assertNotIn("too few to quote", ST.report(s))                 # n = 60: quotable
            self.assertTrue(json.loads(ST.to_json(s))["held_up"]["quotable"])
            os.remove(os.path.join(root, "o__p", "s0", "review.json"))         # n = 59: not
            s = ST.collect(root)
            self.assertIn("n=59 < 60, too few to quote", ST.report(s))
            self.assertFalse(json.loads(ST.to_json(s))["held_up"]["quotable"])

    def test_wilson(self):
        from crucible import stats as ST
        lo, hi = ST.wilson(53, 64)                       # the 11-07 exchange note's figure: 83% is really 72-90%
        self.assertEqual((round(lo, 2), round(hi, 2)), (0.72, 0.90))
        self.assertIsNone(ST.wilson(0, 0))
        self.assertEqual(ST.wilson(5, 5)[1], 1.0)
        self.assertEqual(ST.wilson(0, 5)[0], 0.0)

    def test_cli_since(self):
        with tempfile.TemporaryDirectory() as home:
            self._store(os.path.join(home, "reviews"), "s1", {"finished": "2026-11-06T10:00:00"}, [TestStats._f("CR-1", "t")])
            run = lambda *a: subprocess.run([sys.executable, "-m", "crucible", "stats", *a], capture_output=True,
                                            text=True, env=dict(os.environ, CRUCIBLE_HOME=home),
                                            cwd=os.path.dirname(os.path.dirname(__file__)))
            out = run("--since", "2026-11-06 09:30", "--json")
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(json.loads(out.stdout)["window"]["since"], "2026-11-06T09:30:00")
            self.assertEqual(json.loads(out.stdout)["overall"]["unique"], 1)
            self.assertEqual(run("--since", "2026-11-07").stdout.split(":")[0], "No data")
            bad = run("--since", "yesterday")
            self.assertEqual(bad.returncode, 2)
            self.assertIn("not a date or date-time", bad.stderr)
            self.assertIn("without a zone", run("--since", "2026-11-07T05:00+00:00").stderr)




class TestDraftCitation(unittest.TestCase):
    """gamescope #2516: with `--draft PR_BODY.md`, description findings cited PR_DRAFT.md:1, the verifier was shown
    "(file not present at this commit)", and 4 verifiers refuted findings because "PR_DRAFT.md does not exist"."""

    def test_label(self):
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, "r"); os.makedirs(os.path.join(repo, "notes"))
            self.assertEqual(V.draft_label(repo, None), "PR_DRAFT.md")
            self.assertEqual(V.draft_label(repo, os.path.join(repo, "PR_DRAFT.md")), "PR_DRAFT.md")
            self.assertEqual(V.draft_label(repo, os.path.join(repo, "notes", "body.md")), os.path.join("notes", "body.md"))
            out = os.path.join(d, "elsewhere.md")                       # outside the repo: absolute, so it can be opened
            self.assertEqual(V.draft_label(repo, out), out)
            self.assertEqual(V.draft_label(repo, os.path.join(d, "r..md")), os.path.join(d, "r..md"))

    def test_cite_draft(self):
        repo = make_repo({"CHANGELOG.md": "# Changelog\n", "src/a.c": "int a;\n"})
        self.assertEqual(V.cite_draft({"file": "PR_DRAFT.md"}, "PR_BODY.md", repo)["file"], "PR_BODY.md")
        self.assertEqual(V.cite_draft({"file": "body.md"}, "/x/body.md", repo)["file"], "/x/body.md")
        self.assertEqual(V.cite_draft({"file": "src/a.c"}, "PR_BODY.md", repo)["file"], "src/a.c")
        self.assertEqual(V.cite_draft({"file": "PR_DRAFT.md"}, "PR_DRAFT.md", repo)["file"], "PR_DRAFT.md")
        # a real file that shares the draft's name keeps its finding, also when it's tracked but not on disk
        self.assertEqual(V.cite_draft({"file": "CHANGELOG.md"}, "/x/CHANGELOG.md", repo)["file"], "CHANGELOG.md")
        self.assertEqual(V.cite_draft({"file": "NEWS.md"}, "/x/NEWS.md", repo, {"NEWS.md"})["file"], "NEWS.md")

    def test_draft_file_line(self):
        plain = "Fixes #7\n\nbody line\n"
        self.assertEqual(R.draft_file_line(plain, 3), 3)
        layout = "## Title\n\nset a to 2\n\n## Body\n\nFixes #7\n\nbody line\n\n## Explain it to me\n\nnote\n"
        sub = R.submitted_text(layout).split("\n")
        raw = layout.split("\n")
        for n, t in enumerate(sub, 1):                  # every submitted line maps to the same text in the file
            if t:
                self.assertEqual(raw[R.draft_file_line(layout, n) - 1].strip("` "), t, n)
        h1 = "# Title here\n\n\nFirst body line\n"
        self.assertEqual(R.draft_file_line(h1, 1), 1)
        self.assertEqual(R.draft_file_line(h1, 3), 4)

    def test_region_reads_the_untracked_draft(self):
        repo = make_repo({"a.c": "int a;\n"})
        self.assertEqual(V.region(repo, "HEAD", "PR_BODY.md", 1), "(file not present at this commit)")
        got = V.region(repo, "HEAD", "PR_BODY.md", 1, draft=("PR_BODY.md", "Fixes #1\n\nbody"))
        self.assertIn("    1  Fixes #1", got)
        self.assertIn("int a;", V.region(repo, "HEAD", "a.c", 1, draft=("PR_BODY.md", "x")))

    def test_prompt_wording_unchanged_for_the_default_draft(self):
        # the review cache is keyed on the prompt: the default must not invalidate every cached pass
        ch = {"files": ["a.c"], "text": "diff"}
        p = V.review_prompt("o__r", "a" * 40, "b" * 40, ch, "", "", "", "", ["a.c"])
        self.assertIn('Use file "PR_DRAFT.md" for description findings', p)
        self.assertIn('Use file "PR_BODY.md"', V.review_prompt("o__r", "a" * 40, "b" * 40, ch, "", "", "", "", ["a.c"],
                                                                draft_file="PR_BODY.md"))

    def test_run_review_cites_the_real_draft(self):
        repo = make_repo({"src/a.js": "export const a = 1;\n"}, {"src/a.js": "export const a = 2;\n"})
        open(os.path.join(repo, "PR_BODY.md"), "w").write("## Title\n\nset a to 2\n\n## Body\n\nFixes #7\n\n"
                                                          "Changes a to 2. Tested: npm test\n\n"
                                                          "## Explain it to me\n\nPRIVATE NOTE\n")
        prompts = {"review": [], "verify": []}

        def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
            if "findings" in schema["properties"]:
                prompts["review"].append(prompt)
                return {"summary": "s", "findings": [
                    {"severity": "low", "file": "PR_DRAFT.md", "line": 1, "title": "body doesn't say why a is 2",
                     "problem": "no reason given", "caused_by_this_change": True, "reachable_in_real_use": True,
                     "wrong_if": "the body explains it", "fix": "say why"}]}, 0.01
            prompts["verify"].append(prompt)
            return {"keep": True, "severity": "low", "method": "read", "actions": "read", "evidence": "seen",
                    "confidence": "high"}, 0.001

        home = tempfile.mkdtemp(prefix="crucible-home-")
        olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
        V.HOME = U.HOME = home
        os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
        V.claude = fake
        try:
            out = V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True,
                               draft=os.path.join(repo, "PR_BODY.md"), log=lambda *_: None)
            r = U.read_json(os.path.join(out, "review.json"))
            self.assertEqual(r["status"], "done", r.get("reason"))
            self.assertIn('Use file "PR_BODY.md"', prompts["review"][0])
            files = {f["file"] for f in r["findings"] if f["title"] == "body doesn't say why a is 2"}
            self.assertEqual(files, {"PR_BODY.md"})
            self.assertTrue(prompts["verify"])
            # the reviewer's line 1 (the title) is cited at the file's own line 3, shown with the file's numbering,
            # without the author's notes
            self.assertEqual({f["line"] for f in r["findings"] if f["file"] == "PR_BODY.md" and f["source"] == "review"}, {3})
            self.assertRegex(prompts["verify"][0], r"(?m)^\s*3  set a to 2$")
            self.assertRegex(prompts["verify"][0], r"(?m)^\s*7  Fixes #7$")
            self.assertNotIn("PRIVATE NOTE", prompts["verify"][0])
            self.assertNotIn("file not present", prompts["verify"][0])
            # Lutris #7004: the verifier judged a newer PR_BODY.v2.md instead of the reviewed draft
            self.assertIn("exactly the text of PR_BODY.md", prompts["verify"][0])
            # round 2 changes only code: the carried description finding's re-check is held to the draft too
            open(os.path.join(repo, "src/a.js"), "w").write("export const a = 3;\n")
            sh(repo, "git", "commit", "-qam", "a is 3")
            prompts["verify"].clear()
            out = V.run_review(repo, "main", offline=True, skip_checks=True,
                               draft=os.path.join(repo, "PR_BODY.md"), log=lambda *_: None)
            r = U.read_json(os.path.join(out, "review.json"))
            self.assertEqual(r["status"], "done", r.get("reason"))
            rechecks = [p for p in prompts["verify"] if "changed since then" in p and "PR_BODY.md:" in p]
            self.assertTrue(rechecks, prompts["verify"])
            self.assertTrue(all("exactly the text of PR_BODY.md" in p for p in rechecks))
        finally:
            V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
            if olds[3] is None:
                os.environ.pop("CRUCIBLE_CACHE", None)
            else:
                os.environ["CRUCIBLE_CACHE"] = olds[3]


class TestDraftScope(unittest.TestCase):
    """Lutris #7004 (2026-11-07): the review judged a stale PR_DRAFT.md; the verifier found the newer PR_BODY.v2.md,
    judged that instead and dropped a true finding. The verifier is held to the judged draft, and readiness says when
    a newer body file sits next to it."""
    F = {"title": "t", "file": "a.py", "line": 3, "severity": "low", "wrong_if": "w"}

    def test_verifier_scope_only_for_description_findings(self):
        self.assertEqual(V.verify_prompt(self.F, "code"), V.verify_prompt(self.F, "code", draft_label="PR_DRAFT.md"))
        d = dict(self.F, file="PR_DRAFT.md")
        self.assertIn("exactly the text of PR_DRAFT.md", V.verify_prompt(d, "code", draft_label="PR_DRAFT.md"))
        self.assertNotIn("exactly the text", V.verify_prompt(d, "code"))
        # still a dedented prompt: the inserted text must not break the template's layout
        self.assertRegex(V.verify_prompt(d, "code", draft_label="PR_DRAFT.md"), r"(?m)^Do the falsification test")

    def _repo(self):
        repo = make_repo({"a.py": "a = 1\n"}, {"a.py": "a = 2\n"})
        draft = os.path.join(repo, "PR_DRAFT.md")
        open(draft, "w").write("Fixes #1\n\nold design\n")
        os.utime(draft, (1_700_000_000, 1_700_000_000))
        return repo, draft

    def test_newer_body_file_warns(self):
        repo, draft = self._repo()
        open(os.path.join(repo, "PR_BODY.v2.md"), "w").write("new design\n")
        open(os.path.join(repo, "PR_DRAFT.polished.md"), "w").write("polish proposal\n")  # polish output: never a rival
        open(os.path.join(repo, "PR_DRAFT.polish-notes.md"), "w").write("polish notes\n")
        it = R.newer_draft(repo, draft)
        self.assertEqual(it["status"], "warn", it)
        self.assertIn("PR_BODY.v2.md", it["evidence"])
        self.assertIn("--draft PR_BODY.v2.md", it["evidence"])
        self.assertNotIn("polish", it["evidence"])
        self.assertNotIn("more)", it["evidence"])
        open(os.path.join(repo, "PR_DRAFT_v3.md"), "w").write("newest design\n")
        self.assertIn("(and 1 more)", R.newer_draft(repo, draft)["evidence"])

    def test_body_file_names(self):
        for n in ("PR_BODY.md", "PR_BODY.v2.md", "PR_BODY_v2.md", "PR_DRAFT2.md", "pr-body-final.md",
                  "PULL_REQUEST_DESCRIPTION.md", "PR_DESC.md"):
            self.assertTrue(R.BODY_FILE_RX.match(n), n)
        for n in ("PREP.md", "NOTES.md", "PR_BODY.txt", "pr_bodycheck.md", "PRIVATE.md", "PROPOSAL.md"):
            self.assertFalse(R.BODY_FILE_RX.match(n), n)

    def test_copy_of_the_judged_body_passes(self):
        # open-pr.sh submits PR_BODY.md, written out of the reviewed draft: same text, re-wrapped, is not a rival
        repo, draft = self._repo()
        open(os.path.join(repo, "PR_BODY.md"), "w").write("Fixes #1\n\nold\n   design\n")
        self.assertEqual(R.newer_draft(repo, draft)["status"], "pass", R.newer_draft(repo, draft))
        open(os.path.join(repo, "PR_BODY.md"), "w").write("old design, edited after the review\n")
        self.assertEqual(R.newer_draft(repo, draft)["status"], "warn")
        # a cut-down body is not what was reviewed either (it dropped the Fixes line)
        open(os.path.join(repo, "PR_BODY.md"), "w").write("old design\n")
        self.assertEqual(R.newer_draft(repo, draft)["status"], "warn")
        # the body without the draft's title line is a copy (the title is submitted separately)
        open(draft, "w").write("## Title\n\nFix a\n\n## Body\n\nFixes #1\n\nold design\n\n## Explain it to me\n\nnotes\n")
        os.utime(draft, (1_700_000_000, 1_700_000_000))
        open(os.path.join(repo, "PR_BODY.md"), "w").write("Fixes #1\n\nold design\n")
        self.assertEqual(R.newer_draft(repo, draft)["status"], "pass", R.newer_draft(repo, draft))
        open(os.path.join(repo, "PR_BODY.md"), "w").write("notes\n")        # text from the private notes only
        self.assertEqual(R.newer_draft(repo, draft)["status"], "warn")
        # a byte-for-byte copy of drafts with a heading title or a notes section
        for text in ("# Fix a\n\nFixes #1\n\nold design\n", "Fixes #1\n\nbody\n\n## Explain it to me\n\nnotes\n",
                     open(draft).read()):
            open(draft, "w").write(text)
            os.utime(draft, (1_700_000_000, 1_700_000_000))
            open(os.path.join(repo, "PR_BODY.md"), "w").write(text)
            self.assertEqual(R.newer_draft(repo, draft)["status"], "pass", text)

    def test_older_tracked_or_unrelated_files_pass(self):
        repo, draft = self._repo()
        for n in ("PR_BODY.md", "NOTES.md", "PREP.md", "pr_template_notes.md"):
            open(os.path.join(repo, n), "w").write("x\n")
        os.utime(os.path.join(repo, "PR_BODY.md"), (1_600_000_000, 1_600_000_000))   # older than the draft
        os.makedirs(os.path.join(repo, "docs"))
        open(os.path.join(repo, "PULL_REQUEST_DESCRIPTION.md"), "w").write("tracked\n")
        sh(repo, "git", "add", "PULL_REQUEST_DESCRIPTION.md"); sh(repo, "git", "commit", "-qm", "tracked doc")
        self.assertEqual(R.newer_draft(repo, draft)["status"], "pass", R.newer_draft(repo, draft))
        self.assertEqual(R.newer_draft(repo, None)["status"], "na")

    def test_draft_kept_outside_the_repo(self):
        # the lanes keep drafts in a work dir next to the clone: look beside the draft too
        repo, _ = self._repo()
        work = tempfile.mkdtemp(prefix="crucible-work-")
        draft = os.path.join(work, "PR_DRAFT.md")
        open(draft, "w").write("x\n")
        os.utime(draft, (1_700_000_000, 1_700_000_000))
        open(os.path.join(work, "PR_BODY.v2.md"), "w").write("y\n")
        it = R.newer_draft(repo, draft)
        self.assertEqual(it["status"], "warn", it)
        self.assertIn(os.path.join(work, "PR_BODY.v2.md"), it["evidence"])
        # explicitly judging the newest file is fine
        self.assertEqual(R.newer_draft(repo, os.path.join(work, "PR_BODY.v2.md"))["status"], "pass")

    def test_listed_in_readiness(self):
        repo, draft = self._repo()
        open(os.path.join(repo, "PR_BODY.v2.md"), "w").write("new\n")
        files = [{"path": "a.py", "hunks": [], "added": 1, "removed": 1}]
        items = {i["item"]: i for i in R.evaluate(repo, "o__r", "main", files, draft=draft, offline=True)["items"]}
        self.assertEqual(items["judged draft is the newest PR body"]["status"], "warn")


class TestAIAttribution(unittest.TestCase):
    """DRG-11 bug n (bvh-errors, 2026-11-06 1900): `polish` appended "🤖 Generated with [Claude Code](...)" to a draft
    that had no such line, and reported it only as a leftover emoji. Rule 6: no AI attribution upstream."""
    FOOTER = "🤖 Generated with [Claude Code](https://claude.com/claude-code)"

    def test_lines_detected(self):
        for line in (self.FOOTER, "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>",
                     "Co-authored-by: Copilot <175728472+Copilot@users.noreply.github.com>",
                     "Generated by ChatGPT", "_Written with Cursor_"):
            self.assertEqual(S.attribution_lines(f"Fix x.\n\n{line}\n"), [line], line)

    def test_human_text_not_flagged(self):
        for text in ("Co-authored-by: Jane Doe <jane@example.com>", "Fixes the code generated by the shader compiler.",
                     "The cursor was generated with the wrong offset.", "Uses the Gemini API client from #12.",
                     "Tested with `npm test` (generated with the default fixtures).",
                     "Requires the [Claude Code](https://claude.com/claude-code) CLI.",
                     "See https://claude.ai/code for setup."):
            self.assertEqual(S.attribution_lines(text), [], text)

    def test_polish_drops_attribution_it_added(self):
        d = make_repo({"a.js": "1\n"})
        with open(os.path.join(d, "PR_DRAFT.md"), "w") as fh:
            fh.write("# Fix a\n\nFixes #3.\n\nThe worker swallowed errors.\n")
        orig, logs = S.claude, []
        S.claude = lambda *a, **k: ({"title": "Fix a", "body": f"Fixes #3.\n\nWorker errors now reject.\n\n{self.FOOTER}\n",
                                     "removed": [], "kept_facts": []}, 0.0)
        try:
            S.polish(d, "t__polish_attr", log=logs.append)
        finally:
            S.claude = orig
        txt = open(os.path.join(d, "PR_DRAFT.polished.md")).read()
        self.assertNotIn("Generated with", txt)
        self.assertEqual(txt, "# Fix a\n\nFixes #3.\n\nWorker errors now reject.\n")
        self.assertIn("AI attribution added by the rewrite", open(os.path.join(d, "PR_DRAFT.polish-notes.md")).read())
        self.assertTrue(any("dropped AI attribution" in l for l in logs), logs)
        # the summary judges the text that was written, which no longer has the footer (or its emoji)
        self.assertIn("remaining tells: none", logs[-1])

    def test_polish_matches_the_upstream_issue_url_to_hash_form(self):
        """self-review b6c5466: polish() must pass the upstream slug, or a reworded URL line comes back twice."""
        d = make_repo({"a.js": "1\n"})
        sh(d, "git", "remote", "add", "upstream", "https://github.com/o/r.git")
        with open(os.path.join(d, "PR_DRAFT.md"), "w") as fh:
            fh.write("# Fix a\n\nThe worker swallowed errors.\n\nCloses https://github.com/o/r/issues/12\n")
        orig = S.claude
        S.claude = lambda *a, **k: ({"title": "Fix a", "body": "Worker errors now reject.\n\nCloses #12\n",
                                     "removed": [], "kept_facts": []}, 0.0)
        try:
            S.polish(d, "t__polish_slug", log=lambda *_: None)
        finally:
            S.claude = orig
        self.assertEqual(open(os.path.join(d, "PR_DRAFT.polished.md")).read(),
                         "# Fix a\n\nWorker errors now reject.\n\nCloses https://github.com/o/r/issues/12\n")

    def test_polish_keeps_disclosure_the_author_wrote(self):
        # a project that asks for AI disclosure gets the author's own line back; polish only removes what it invented
        body, removed = S.strip_new_attribution("Fix.\n\nCo-authored-by: Claude <noreply@anthropic.com>",
                                                "Fix, tidier.\n\nCo-authored-by: Claude <noreply@anthropic.com>")
        self.assertEqual(removed, [])
        self.assertIn("Co-authored-by: Claude", body)

    def test_review_flags_draft_attribution_at_its_line(self):
        found = S.check(".", "HEAD", [], "PR_DRAFT.md", f"Fix a\n\nBody.\n\n{self.FOOTER}", {}, title="Fix a")
        f = [x for x in found if "attribution" in x["title"]]
        self.assertEqual(len(f), 1, found)
        self.assertEqual((f[0]["severity"], f[0]["line"]), ("medium", 5))
        self.assertFalse([x for x in found if "emoji" in x["title"]], found)  # the footer's 🤖 is the same finding
        self.assertFalse([x for x in S.check(".", "HEAD", [], "PR_DRAFT.md", "Fix a\n\nBody.", {}) if "attribution" in x["title"]])

    def test_readiness_warns_on_commit_trailer(self):
        d = make_repo({"a.js": "1\n"}, {"a.js": "2\n"},
                      msg="Fix a\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
        base = U.git(d, "merge-base", "main", "HEAD")
        item = R.commit_attribution(d, base)
        self.assertEqual(item["status"], "warn")
        self.assertIn("noreply@anthropic.com", item["evidence"])
        self.assertIn("no AI tool attribution in commits", [i["item"] for i in R.evaluate(d, "t__attr", base, [], offline=True)["items"]])
        clean = make_repo({"a.js": "1\n"}, {"a.js": "2\n"}, msg="Fix a\n\nCo-authored-by: Jane <j@example.com>")
        self.assertEqual(R.commit_attribution(clean, U.git(clean, "merge-base", "main", "HEAD"))["status"], "pass")

    def test_run_review_cites_the_footer_at_the_draft_files_line(self):
        repo = make_repo({"src/a.js": "export const a = 1;\n"}, {"src/a.js": "export const a = 2;\n"})
        open(os.path.join(repo, "PR_BODY.md"), "w").write("## Title\n\nset a to 2\n\n## Body\n\nFixes #7\n\n"
                                                          f"Tested: npm test\n\n{self.FOOTER}\n")
        home = tempfile.mkdtemp(prefix="crucible-home-")
        olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
        V.HOME = U.HOME = home
        os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
        V.claude = lambda *a, **k: ({"summary": "s", "findings": []}, 0.0)
        try:
            out = V.run_review(repo, "main", offline=True, skip_checks=True, no_tiers=True,
                               draft=os.path.join(repo, "PR_BODY.md"), log=lambda *_: None)
            r = U.read_json(os.path.join(out, "review.json"))
            f = [x for x in r["findings"] if "attribution" in x["title"]]
            self.assertEqual([(x["file"], x["line"]) for x in f], [("PR_BODY.md", 11)], r["findings"])
        finally:
            V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
            if olds[3] is None:
                os.environ.pop("CRUCIBLE_CACHE", None)
            else:
                os.environ["CRUCIBLE_CACHE"] = olds[3]


class TestAnchorReplay(unittest.TestCase):
    """`crucible anchor-replay`: today's verifier prompt vs the same prompt plus the reviewer's argument."""
    F = {"id": "CR-1", "title": "Off by one", "file": "a.py", "line": 2, "severity": "low", "source": "review",
         "wrong_if": "the loop stops at len-1", "problem": "PERSUASIVE ARGUMENT", "fix": "use <="}

    def test_prompt_withholds_the_argument_unless_asked(self):
        plain = V.verify_prompt(self.F, "CODE")
        self.assertNotIn("PERSUASIVE ARGUMENT", plain)
        withp = V.verify_prompt(self.F, "CODE", argument=True)
        self.assertIn("Problem: PERSUASIVE ARGUMENT", withp)
        self.assertLess(withp.index("PERSUASIVE"), withp.index("Code around the cited line"))
        # the default prompt is unchanged by the flag, so verdicts cached before it still match
        self.assertEqual(withp.replace(withp[withp.index("The reviewer's argument"):withp.index("Code around")], ""), plain)

    def _store(self, root, repo, sha, findings, answers, started):
        d = os.path.join(root, repo, sha)
        os.makedirs(d)
        U.write_json(os.path.join(d, "review.json"), {"repo": repo, "sha": sha, "status": "done", "started": started,
                                                      "findings": findings, "inputs": {"draft": "/x/PR_BODY.md"}})
        U.write_json(os.path.join(d, "answers.json"), answers)

    def test_answered_takes_the_earliest_round_and_skips_the_rest(self):
        from crucible import anchoring as A
        f2 = dict(self.F, id="CR-2", file="PR_BODY.md")
        sc = dict(self.F, id="SC-1", source="scanner")
        with tempfile.TemporaryDirectory() as root:
            self._store(root, "o__p", "s2", [self.F], {"CR-1": {"disposition": "fixed"}}, "2026-11-06")
            self._store(root, "o__p", "s1", [self.F, f2, sc, dict(self.F, id="CR-3")],
                        {"CR-1": {"disposition": "fixed"}, "CR-2": {"disposition": "refuted"},
                         "SC-1": {"disposition": "refuted"}}, "2026-11-05")
            self._store(root, "JROtto5__crucible", "c1", [self.F], {"CR-1": {"disposition": "refuted"}}, "2026-11-05")
            es = A.answered(root)
            self.assertEqual([(e["finding"]["id"], e["sha"]) for e in es], [("CR-1", "s1"), ("CR-2", "s1")])
            self.assertEqual([A.on_draft(e) for e in es], [False, True])     # the draft's text isn't stored
            self.assertEqual(len(A.answered(root, include_self=True)), 3)

    def test_sample_is_even_and_deterministic(self):
        from crucible import anchoring as A
        es = [{"disposition": "refuted", "n": i} for i in range(3)] + [{"disposition": "fixed", "n": i} for i in range(10)]
        s = A.sample(es, 2)
        self.assertEqual([(e["disposition"], e["n"]) for e in s], [("refuted", 0), ("refuted", 1), ("fixed", 0), ("fixed", 5)])
        self.assertEqual(len(A.sample(es, 0)), 13)

    def test_tally_counts_false_alarms_kept_and_real_dropped(self):
        from crucible import anchoring as A
        es = [{"repo": "o__p", "disposition": d, "finding": dict(self.F, id=i)}
              for d, i in (("refuted", "R"), ("fixed", "F"), ("deferred", "D"))]

        def verify(r, argument):        # with the argument the verifier is anchored: keeps everything
            if r["finding"]["id"] == "D" and not argument:
                raise U.Failed("usage limit")
            return (True if argument else r["finding"]["id"] == "F"), 0.25
        t = A.tally(A.judge(es, verify, jobs=2))
        # paired: D failed in one arm, so it is left out of both and the arms compare the same two findings
        self.assertEqual({k: t["with"][k] for k in ("false_alarms_kept", "refuted", "real_dropped", "real", "failed")},
                         {"false_alarms_kept": 1, "refuted": 1, "real_dropped": 0, "real": 1, "failed": 0})
        self.assertEqual({k: t["without"][k] for k in ("false_alarms_kept", "refuted", "real_dropped", "real", "failed")},
                         {"false_alarms_kept": 0, "refuted": 1, "real_dropped": 0, "real": 1, "failed": 1})
        self.assertEqual(t["excluded"], 1)
        self.assertAlmostEqual(t["with"]["cost"], 0.75)
        self.assertIn("R [refuted] without: dropped, with: kept", A.report(A.judge(es, verify), {}))

    def test_budget_stops_are_counted_apart_from_failed_calls(self):
        from crucible import anchoring as A
        es = [{"repo": "o__p", "disposition": "fixed", "finding": dict(self.F, id=i)} for i in ("A", "B", "C")]

        def verify(r, argument):        # A: a real failure; B: the run's --budget ran out; C: judged
            if r["finding"]["id"] == "A" and argument:
                raise U.Failed("usage limit")
            if r["finding"]["id"] == "B" and argument:
                raise U.Failed("budget exhausted")
            return True, 0.1
        rows = A.judge(es, verify, jobs=1)
        t = A.tally(rows)
        self.assertEqual((t["with"]["failed"], t["with"]["budget"], t["without"]["budget"]), (2, 1, 0))
        out = A.report(rows, {})
        self.assertIn("failed calls 2 (1 stopped by --budget)", out)
        self.assertNotIn("stopped by --budget", out.split("- without")[1].split("\n")[0])

    def test_sample_is_taken_from_replayable_findings_only(self):
        from unittest import mock
        from crucible import anchoring as A
        repo = shutil.move(make_repo({"a.py": "x = 1\n"}, {"a.py": "x = 2\n"}), tempfile.mkdtemp())   # don't walk all of /tmp
        sha = sh(repo, "git", "rev-parse", "HEAD")
        with tempfile.TemporaryDirectory() as root:
            # "o__a" sorts first and its commit is in no clone: sampling first would spend the one slot on it
            self._store(root, "o__a", "e" * 40, [self.F], {"CR-1": {"disposition": "refuted"}}, "2026-11-05")
            self._store(root, "o__p", sha, [self.F], {"CR-1": {"disposition": "refuted"}}, "2026-11-05")
            with mock.patch.object(V, "verify_tiered", lambda *a, **k: ({"keep": False}, [])):
                rows, skipped = A.run(root, [os.path.dirname(repo)], per_class=1)
        self.assertEqual([r["repo"] for r in rows], ["o__p"])
        self.assertEqual(skipped["no local clone has the commit"], 1)

    def test_cli_passes_its_flags_through(self):
        from unittest import mock
        from crucible import anchoring as A, cli
        with mock.patch.object(A, "run", return_value=([], {})) as run, mock.patch("builtins.print"):
            cli.main(["anchor-replay", "--clones", "/c1", "/c2", "--per-class", "2", "--jobs", "3", "--budget", "1.5"])
        self.assertEqual(run.call_args.args, (os.path.join(U.HOME, "reviews"), ["/c1", "/c2"], 2, 3, 1.5, False, 1))
        with mock.patch.object(A, "run", return_value=([], {})) as run, mock.patch("builtins.print"):
            cli.main(["anchor-replay", "--clones", "/c1", "--votes", "2"])
        self.assertEqual(run.call_args.args[-1], 2)
        for bad in ("0", "-1", "two"):
            with mock.patch.object(A, "run") as run, mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                cli.main(["anchor-replay", "--clones", "/c1", "--votes", bad])
            run.assert_not_called()

    def test_two_votes_keep_only_what_both_keep(self):
        """2026-11-07: a plain re-verify dropped 5 of 10 author-refuted findings the first verification had kept. With
        --votes 2 a finding survives an arm only if both fresh verdicts keep it, and the report shows the first vote
        alone and how often the votes split, so the gain over one vote is read off the same run."""
        from crucible import anchoring as A
        es = [{"repo": "o__p", "disposition": d, "finding": dict(self.F, id=i)}
              for d, i in (("refuted", "R"), ("fixed", "F"), ("refuted", "X"))]
        calls = {}

        def verify(r, argument):        # R: keep then drop (noise); F: always kept; X: second vote fails
            i = r["finding"]["id"]
            n = calls[(i, argument)] = calls.get((i, argument), 0) + 1
            if i == "X" and n == 2:
                raise U.Failed("usage limit")
            return (n == 1 if i == "R" else True), 0.1
        rows = A.judge(es, verify, jobs=3, votes=2)
        self.assertEqual(calls, {("R", False): 2, ("R", True): 2, ("F", False): 2, ("F", True): 2,
                                 ("X", False): 2, ("X", True): 2})
        by = {r["finding"]["id"]: r["arms"]["without"] for r in rows}
        self.assertEqual((by["R"]["keep"], by["R"]["votes"]), (False, [True, False]))
        self.assertEqual((by["X"]["keep"], by["X"]["votes"]), (None, [True]))
        self.assertAlmostEqual(by["X"]["cost"], 0.1)        # the vote that ran is still paid for
        t = A.tally(rows)
        self.assertEqual(t["excluded"], 1)
        s = t["without"]
        self.assertEqual((s["false_alarms_kept"], s["refuted"], s["real_dropped"], s["real"], s["split"]), (0, 1, 0, 1, 1))
        self.assertEqual(s["first"], {"false_alarms_kept": 1, "refuted": 1, "real_dropped": 0, "real": 1})
        text = A.report(rows, {}, votes=2)
        self.assertIn("2 votes per arm", text)
        self.assertIn("first vote alone: false alarms still kept 1/1, real findings dropped 0/1; votes split on 1/2", text)
        self.assertNotIn("first vote alone", A.report(A.judge(es[:2], lambda r, a: (True, 0)), {}))

    def test_checkout_of_a_partial_clone_fetches_into_the_temp_repo_only(self):
        from crucible import anchoring as A
        up = make_repo({"a.py": "x = 1\n"}, {"a.py": "x = 2\n"})
        sha = sh(up, "git", "rev-parse", "HEAD")
        with tempfile.TemporaryDirectory() as tmp:
            clone = os.path.join(tmp, "clone")
            sh(tmp, "git", "-c", "uploadpack.allowFilter=true", "clone", "-q", "--no-checkout", "--filter=blob:none",
               "file://" + up, clone)
            sh(up, "git", "config", "uploadpack.allowFilter", "true")
            before = sh(clone, "git", "count-objects", "-v")
            tree = A.checkout(clone, sha, os.path.join(tmp, "t"))
            with open(os.path.join(tree, "a.py")) as fh:
                self.assertEqual(fh.read(), "x = 2\n")
            self.assertEqual(sh(tree, "git", "config", "remote.origin.promisor"), "true")
            self.assertEqual(sh(clone, "git", "count-objects", "-v"), before)     # the blob landed in the temp repo

    def test_commit_lookup_never_fetches_from_a_promisor_remote(self):
        from unittest import mock
        from crucible import anchoring as A
        with mock.patch.object(A.subprocess, "run", return_value=mock.Mock(returncode=1)) as run:
            self.assertFalse(A.has_commit("/clone", "abc"))
        self.assertEqual(run.call_args.kwargs["env"].get("GIT_NO_LAZY_FETCH"), "1")

    def test_run_checks_out_the_reviewed_commit_without_touching_the_clone(self):
        from unittest import mock
        from crucible import anchoring as A
        repo = shutil.move(make_repo({"a.py": "x = 1\n"}, {"a.py": "x = 2\ny = 3\n"}), tempfile.mkdtemp())
        sha = sh(repo, "git", "rev-parse", "HEAD")
        sh(repo, "git", "commit", "-q", "--amend", "-m", "amended")     # the reviewed round is reachable from no ref
        sh(repo, "git", "checkout", "-q", "main")
        before = sh(repo, "git", "worktree", "list") + sh(repo, "git", "status", "--porcelain")
        seen = []

        def fake_verify(f, code, tree, budget, tiers, fresh=False, argument=False, **kw):
            with open(os.path.join(tree, "a.py")) as fh:
                text = fh.read()
            seen.append((text, code.count("y = 3"), argument, fresh,
                         os.environ["CRUCIBLE_CACHE"].startswith(tempfile.gettempdir())))
            return {"keep": argument}, [{"cost": 0.1}]
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as other:
            self._store(root, "o__p", sha, [self.F, dict(self.F, id="CR-2", file="PR_BODY.md")],
                        {"CR-1": {"disposition": "refuted"}, "CR-2": {"disposition": "fixed"}}, "2026-11-05")
            self._store(root, "o__q", "f" * 40, [dict(self.F, id="CR-9")], {"CR-9": {"disposition": "fixed"}}, "2026-11-05")
            os.environ.pop("CRUCIBLE_CACHE", None)
            with mock.patch.object(V, "verify_tiered", fake_verify):
                rows, skipped = A.run(root, [os.path.dirname(repo), other])
            self.assertNotIn("CRUCIBLE_CACHE", os.environ)
        self.assertEqual(skipped, {"on the PR draft (its text isn't stored)": 1, "no local clone has the commit": 1,
                                   "the commit couldn't be checked out": 0})
        self.assertEqual(sorted(seen), [("x = 2\ny = 3\n", 1, False, True, True), ("x = 2\ny = 3\n", 1, True, True, True)])
        self.assertEqual(sh(repo, "git", "worktree", "list") + sh(repo, "git", "status", "--porcelain"), before)
        self.assertEqual(A.tally(rows)["with"]["false_alarms_kept"], 1)


class TestLengthLeftToHouseCheck(unittest.TestCase):
    """2026-11-08: 45 model findings on upstream reviews complained about the PR body's length, and the verifier
    dropped 36 of them. The measured check (style.ai_tells) owns length; the reviewer is no longer asked to judge it,
    and a model finding that is only about length is dropped by rule, without a verifier call."""

    # real titles from stored upstream reviews: 10 dropped by the verifier, 1 refuted, 1 fixed (all low)
    REAL = ["PR body is about twice the project's median length", "Description is well above the project's usual length",
            "PR body is well above the project's length norm", "PR description is about 3× longer than the project norm",
            "PR body is longer than the project norm", "PR description is about 3x the project's median length",
            "PR body is about 3x the project's usual length", "Description is about 3x the project's median length",
            "PR body is far longer than the project norm", "PR description is several times the project's length norm",
            "PR body is about 15x this project's median length", "PR body is far longer than project norm"]
    # real titles that say something more, plus ones that only look like length: these are verified as usual
    KEEP = ["Description still has a PROOF_LINE placeholder, says nothing on how it was tested, and is long for t",
            "PR body is long prose instead of the project's short bullet style",
            "PR description is long and uses a table, which the project's PRs don't",
            "PR body is ~300 words with a table, against a project norm of ~19 words",
            "Description is ~150 words against a project median of 19 (p75 50)",
            "PR title/body longer than project norm; title names only `start`",
            "PR body uses first person and is long for this project",
            "Commit has no body and title is far over house length",
            "Description breaks the project's heading norm", "PR body is below the median", "Description overstates the fix",
            "PR body claims 3x speedup without numbers", "Description says the loop is too long",
            # self-review round 1: content claims that only share words with a length complaint
            "Description misstates the long-standing project behaviour", "Body says the project is long-lived",
            "Description says the timeout is longer than the usual 30 s", "PR body: the median is computed wrong",
            "Description is wrong: the loop is longer than usual"]

    def _f(self, title, file="PR_DRAFT.md", source="review", severity="low"):
        return {"title": title, "file": file, "source": source, "severity": severity}

    def test_titles(self):
        for t in self.REAL:
            self.assertTrue(V.length_only(self._f(t), "PR_DRAFT.md"), t)
        for t in self.KEEP:
            self.assertFalse(V.length_only(self._f(t), "PR_DRAFT.md"), t)

    def test_only_model_findings_on_the_judged_draft(self):
        t = self.REAL[0]
        self.assertFalse(V.length_only(self._f(t, source="style"), "PR_DRAFT.md"))   # the measured check itself
        self.assertFalse(V.length_only(self._f(t, file="src/a.js"), "PR_DRAFT.md"))
        self.assertFalse(V.length_only(self._f(t, file="PR_BODY.md"), "PR_DRAFT.md"))
        self.assertFalse(V.length_only(self._f(t), None))
        self.assertTrue(V.length_only(self._f(t, file="/w/PR_DRAFT.md"), "/w/PR_DRAFT.md"))
        self.assertFalse(V.length_only(self._f(t, severity="medium"), "PR_DRAFT.md"))    # above low: verified

    def test_prompt_leaves_length_to_the_check(self):
        args = ("o__r", "a" * 40, "b" * 40, {"files": ["a.py"], "text": "diff"}, "", "", "", "", ["a.py"])
        p = V.review_prompt(*args)
        self.assertNotIn("length far from the project norm", p)
        self.assertRegex(p, r"generated-\s+sounding prose\. Don't report the description's length")
        # nothing learned: the length check can't judge, so the reviewer still does
        p = V.review_prompt(*args, length_measured=False)
        self.assertIn("Also flag length far from the project norm.", p)
        self.assertNotIn("Don't report the description's length", p)
        self.assertTrue(V.length_measured({"body": {"median_words": 40}}))
        self.assertTrue(V.length_measured({"body": {"outside_median_words": 40}}))
        for sj in (None, {}, {"body": {}}, {"body": {"median_words": None}}):
            self.assertFalse(V.length_measured(sj), sj)

    def test_end_to_end_no_verifier_call(self):
        r, verified, report = self._run(learned=True)
        self.assertEqual(verified, ["PR body is long and uses a table"])
        self.assertEqual([f["title"] for f in r["findings"] if f["source"] == "review"], ["PR body is long and uses a table"])
        ruled = [f for f in r["dropped"] if f["verification"].get("method") == "rule"]
        self.assertEqual([f["title"] for f in ruled], ["PR body is about 3x the project's median length"])
        self.assertEqual(ruled[0]["verification"]["status"], "dropped")
        self.assertIn("not sent to the verifier", report)

    def test_end_to_end_not_learned_verifies_as_before(self):
        r, verified, _ = self._run(learned=False)
        self.assertEqual(sorted(verified), ["PR body is about 3x the project's median length", "PR body is long and uses a table"])
        self.assertFalse([f for f in r["dropped"] if f["verification"].get("method") == "rule"])

    def _run(self, learned):
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            repo, home = os.path.join(d, "r"), os.path.join(d, "home")
            os.makedirs(repo)
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env)
            w = lambda p, t: open(os.path.join(repo, p), "w").write(t)
            g("init", "-q", "-b", "main"); w("a.js", "export const a = 1;\n"); g("add", "-A"); g("commit", "-qm", "base")
            g("checkout", "-qb", "x"); w("a.js", "export const a = 2;\n"); g("commit", "-qam", "a is 2")
            draft = os.path.join(d, "PR_DRAFT.md")
            open(draft, "w").write("Fixes #1\n\nSets a to 2. Tested with `npm test`.\n")

            def finding(path, title):
                return {"severity": "low", "file": path, "line": 1, "title": title, "problem": "p",
                        "caused_by_this_change": True, "reachable_in_real_use": True, "wrong_if": "w", "fix": "x"}
            verified = []

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                if "findings" in schema["properties"]:
                    return {"summary": "s", "findings": [finding(draft, "PR body is about 3x the project's median length"),
                                                         finding(draft, "PR body is long and uses a table")]}, 0
                verified.append(re.search(r"Claim: (.*?) \(at", prompt).group(1))
                return {"keep": True, "severity": "low", "confidence": "high", "method": "read", "actions": "a",
                        "evidence": "e"}, 0

            with mock.patch.object(V, "HOME", home), mock.patch.object(U, "HOME", home), \
                    mock.patch.object(V, "claude", fake), mock.patch.dict(os.environ, {"CRUCIBLE_CACHE": os.path.join(home, "c")}):
                if learned:
                    pd = U.project_dir(V.project_key(repo))
                    os.makedirs(pd, exist_ok=True)
                    json.dump({"body": {"median_words": 40}}, open(os.path.join(pd, "style.json"), "w"))
                out = V.run_review(repo, "main", offline=True, skip_checks=True, draft=draft, log=lambda *_: None)
                r = U.read_json(os.path.join(out, "review.json"))
            self.assertEqual(r["status"], "done", r.get("reason"))
            return r, verified, V.report(r, {})

    def _store_rule_drop(self, root):
        p = os.path.join(root, "o__p", "s1")
        os.makedirs(p)
        mk = lambda i, v: {"id": i, "source": "review", "severity": "low", "title": "t", "file": "a.js", "verification": v}
        json.dump({"repo": "r", "base": "b", "started": "2026-11-08T01", "status": "done", "cost_usd": 0.1,
                   "inputs": {}, "files": ["a.js"], "findings": [],
                   "dropped": [mk("CR-1", {"status": "dropped", "method": "rule", "evidence": "e"}),
                               mk("CR-2", {"status": "dropped", "method": "read", "evidence": "e"})]},
                  open(os.path.join(p, "review.json"), "w"))

    def test_routing_replay_does_not_count_a_rule_drop_as_refuted(self):
        with tempfile.TemporaryDirectory() as root:
            self._store_rule_drop(root)
            self.assertEqual((RT.replay(root)["raw"], RT.replay(root)["dropped"]), (1, 1))

    def test_stats_does_not_count_a_rule_drop(self):
        from crucible import stats as ST
        with tempfile.TemporaryDirectory() as root:
            self._store_rule_drop(root)
            o = ST.collect(root)["overall"]
            self.assertEqual((o["unique"], o["dropped"]), (1, 1))   # only the verifier's drop is counted


class TestBodyWordsSkipsFoldedCode(unittest.TestCase):
    """three-mesh-bvh #958 (2026-11-07): the length check counted 383 words and raised a medium; the author refuted
    it, since 155 words were visible prose and the rest a benchmark script folded in <details>."""

    def test_fenced_code_and_details_dont_count(self):
        prose = "Packs the geometry with strided writes."
        self.assertEqual(S.body_words(prose), 6)
        code = "```js\n" + "const a = b + c; // " * 50 + "\n```\n"
        self.assertEqual(S.body_words(prose + "\n\n" + code), 6)
        self.assertEqual(S.body_words(prose + "\n\n~~~\n" + "x y z\n" * 30 + "~~~\n"), 6)
        folded = "<details><summary>Benchmark script</summary>\n\n" + "word " * 200 + "\n</details>\n"
        self.assertEqual(S.body_words(prose + "\n\n" + folded), 8)            # the summary is still read
        self.assertEqual(S.body_words(prose + "\n<DETAILS>\n" + "word " * 50 + "\n</DETAILS>\nAfter."), 7)
        self.assertEqual(S.body_words(prose + " Uses `npm test` too."), 10)   # inline code is prose

    def test_unclosed_blocks_still_count(self):
        # falsifiers: nothing is dropped unless the block is closed
        self.assertEqual(S.body_words("```js\nx y z\n"), 4)
        self.assertEqual(S.body_words("<details>\nx y z\n"), 4)
        # an unclosed fence isn't closed by a later opener: the prose between them still counts
        self.assertEqual(S.body_words("```\nx\n\nprose here\n\n```js\ny\n"), 5)
        # an unclosed outer <details> around a closed inner one: only the inner block folds
        self.assertEqual(S.body_words("<details>\nprose prose\n<details>\nhidden hidden\n</details>\nafter after\n"), 5)

    def test_nested_and_sequential_blocks(self):
        self.assertEqual(S.body_words("a <details>x x</details> mid mid <details>y y</details> end"), 4)
        nested = "Intro.\n<details><summary>Outer</summary>\nx x\n<details><summary>Inner</summary>\ny y\n</details>\nz z\n</details>\nEnd."
        self.assertEqual(S.body_words(nested), 3)                     # Intro, Outer, End
        self.assertEqual(S.body_words("Intro.\n````md\n```js\ncode code\n```\nmore more\n````\nEnd."), 2)
        self.assertEqual(S.body_words("Intro.\n```\n~~~\ncode\n```\nEnd."), 2)   # ~~~ doesn't close ```
        # self-review round 3: tags quoted as inline code are prose, and fold nothing between them
        self.assertEqual(S.body_words("Wraps it in `<details>` so the long log folds; closes with `</details>`."), 12)
        # self-review round 4: a real fold still folds next to, or around, a quoted tag
        self.assertEqual(S.body_words("Mentions `<details>` here.\n<details>\nhidden hidden\n</details>\nEnd."), 4)
        self.assertEqual(S.body_words("<details><summary>S</summary>use `<details>` here x x x x</details>"), 1)
        self.assertEqual(S.body_words("<details><summary>Use `<b>` tags</summary>\nx x\n</details>"), 3)

    def test_folded_code_no_longer_trips_the_length_check(self):
        style = {"body": {"outside_median_words": 144, "outside_prs": 14}}
        body = "word " * 150 + "\n\n<details><summary>Benchmark</summary>\n\n```js\n" + "a b c d\n" * 60 + "```\n</details>\n"
        self.assertFalse([k for k, _ in S.ai_tells(body, style) if k == "length"])
        self.assertTrue([k for k, _ in S.ai_tells("word " * 400, style) if k == "length"])



class TestTokenMetering(unittest.TestCase):
    """BLAZE exchange 2026-11-09: the shared headline is tokens per held-up finding. Each model call's usage is kept
    per model, summed into review.json (review passes vs verification), and `stats` prints tokens per review and per
    held-up finding. A review without complete counts is "not recorded", never 0."""

    @staticmethod
    def _run(payloads):
        from unittest import mock
        it = iter(payloads)

        def fake_run(cmd, **kw):
            p = next(it)
            if p == "timeout":
                raise subprocess.TimeoutExpired(cmd, 1)
            return subprocess.CompletedProcess(cmd, 0, p if isinstance(p, str) else json.dumps(p), "")
        b = U.Budget(None)
        with mock.patch.object(U.subprocess, "run", fake_run):
            for _ in payloads:
                try:
                    U.claude("p", "req-model", {"type": "object"}, ".", b)
                except U.Failed:
                    pass
        return b

    def test_claude_meters_usage_per_model(self):
        ok = {"structured_output": {}, "total_cost_usd": 0.1}
        b = self._run([
            # modelUsage wins over usage and keeps every model the CLI used
            dict(ok, usage={"input_tokens": 999}, modelUsage={
                "opus": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 100, "cacheCreationInputTokens": 20},
                "haiku": {"inputTokens": 1, "outputTokens": 2}}),
            # top-level usage only: filed under the requested model
            dict(ok, usage={"input_tokens": 3, "output_tokens": 4, "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 7}),
            # a failed call that still reports usage is metered (its tokens were spent)
            {"is_error": True, "subtype": "error_max_turns", "modelUsage": {"opus": {"outputTokens": 1}}},
            ok,                       # no usage at all
            "not json",               # unreadable output
            "[]",                     # JSON, but not an object: Failed, not an AttributeError
            "timeout",
        ])
        tokens, unmetered, _ = b.token_snapshot()
        self.assertEqual(tokens, {
            "opus": {"input": 10, "output": 6, "cache_read": 100, "cache_creation": 20},
            "haiku": {"input": 1, "output": 2, "cache_read": 0, "cache_creation": 0},
            "req-model": {"input": 3, "output": 4, "cache_read": 0, "cache_creation": 7}})
        self.assertEqual(unmetered, 4)
        self.assertAlmostEqual(b.spent, 0.3)
        s = U.token_summary(tokens, unmetered)
        self.assertEqual((s["total"], s["input"], s["output"], s["cache_read"], s["cache_creation"]),
                         (153, 14, 12, 100, 27))
        self.assertEqual(s["unmetered_calls"], 4)

    def test_tool_less_calls_run_uncached(self):
        """A one-request call never re-reads its cache, so it runs with prompt caching off; tool loops keep it, and
        CRUCIBLE_NO_TOOLS_CACHE=1 turns it back on for tool-less calls."""
        from unittest import mock
        seen = []

        def fake_run(cmd, **kw):
            seen.append(kw["env"].get("DISABLE_PROMPT_CACHING"))
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"structured_output": {}, "total_cost_usd": 0}), "")

        with mock.patch.object(U.subprocess, "run", fake_run), \
                mock.patch.dict(os.environ, {"DISABLE_PROMPT_CACHING": ""}):
            os.environ.pop("DISABLE_PROMPT_CACHING")
            os.environ.pop("CRUCIBLE_NO_TOOLS_CACHE", None)
            U.claude("p", "m", {"type": "object"}, ".", tools=None)
            U.claude("p", "m", {"type": "object"}, ".", tools=[])
            U.claude("p", "m", {"type": "object"}, ".")                      # default: read tools
            U.claude("p", "m", {"type": "object"}, ".", tools=U.TOOLS_RUN)
            os.environ["CRUCIBLE_NO_TOOLS_CACHE"] = "1"
            U.claude("p", "m", {"type": "object"}, ".", tools=None)
        self.assertEqual(seen, ["1", "1", None, None, None])

    def test_review_and_verify_split(self):
        b = U.Budget(None)
        b.meter({"m": {"input": 1, "output": 1, "cache_read": 0, "cache_creation": 0}})   # before the passes
        before = b.token_snapshot()
        b.meter({"m": {"input": 10, "output": 5, "cache_read": 0, "cache_creation": 0}})
        b.meter(None)
        b.cached_call()
        after = b.token_snapshot()
        b.meter({"v": {"input": 2, "output": 2, "cache_read": 4, "cache_creation": 0}})
        b.cached_call(); b.cached_call()
        t = V.token_fields(b, (before, after))
        self.assertEqual((t["tokens_review"]["total"], t["tokens_review"]["unmetered_calls"]), (15, 1))
        self.assertEqual((t["tokens_review"]["cached_calls"], t["tokens_verify"]["cached_calls"]), (1, 2))
        self.assertEqual(t["tokens_review"]["by_model"], {"m": {"input": 10, "output": 5, "cache_read": 0, "cache_creation": 0}})
        self.assertEqual((t["tokens_verify"]["total"], t["tokens_verify"]["unmetered_calls"]), (10, 0))
        self.assertEqual(set(t["tokens_verify"]["by_model"]), {"m", "v"})
        # failed before the passes: everything is on the verify side, nothing is lost
        t = V.token_fields(b, None)
        self.assertEqual((t["tokens_review"]["total"], t["tokens_verify"]["total"]), (0, 25))
        rev = {"tokens_review": {"total": 1500, "unmetered_calls": 0}, "tokens_verify": {"total": 25, "unmetered_calls": 1}}
        self.assertEqual(V.tokens_note(rev), " · at least 1,525 tokens (review 1,500, verify 25; 1 call(s) without a token count)")
        self.assertEqual(V.tokens_note({"cost_usd": 1}), "")

    def test_tokens_and_cost_per_call_kind(self):
        # BLAZE 11-10 "caching off for one-shot calls that never re-read": the A/B needs the cache-write vs read
        # split per call kind, which review/verify-by-model metering could not give (salvage hid in "verify")
        from unittest import mock
        u = {"structured_output": {}, "total_cost_usd": 0.25,
             "modelUsage": {"m": {"inputTokens": 1, "outputTokens": 2, "cacheReadInputTokens": 30,
                                  "cacheCreationInputTokens": 40}}}
        outs = iter([json.dumps(u), json.dumps(u), json.dumps(u), "not json"])
        b = U.Budget(None)
        with mock.patch.object(U.subprocess, "run",
                               lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, next(outs), "")):
            U.claude("p", "m", {}, ".", b, kind="review")
            U.claude("p", "m", {}, ".", b, kind="review")
            U.claude("p", "m", {}, ".", b, tools=None, kind="salvage")
            with self.assertRaises(U.Failed):
                U.claude("p", "m", {}, ".", b, tools=None, kind="salvage")
        b.cached_call("review")
        k = b.kind_snapshot()
        self.assertEqual(sorted(k), ["review", "salvage"])
        self.assertEqual((k["review"]["calls"], k["review"]["cost_usd"], k["review"]["cache_creation"],
                          k["review"]["cache_read"], k["review"]["no_tools"], k["review"]["cached_calls"]),
                         (2, 0.5, 80, 60, False, 1))
        self.assertEqual((k["salvage"]["calls"], k["salvage"]["unmetered_calls"], k["salvage"]["no_tools"],
                          k["salvage"]["output"]), (2, 1, True, 2))
        # the per-kind counts add up to the per-model ones: nothing is metered twice or dropped
        tokens, unmetered, cached = b.token_snapshot()
        self.assertEqual(sum(v["cache_creation"] for v in k.values()), tokens["m"]["cache_creation"])
        self.assertEqual((unmetered, cached), (1, 1))
        self.assertEqual(V.token_fields(b, None)["tokens_by_kind"], k)

    def test_verify_kind_by_role(self):
        # self-review CR-14ebebac: the last tier was always "verify", so the cheap tier run alone (a routed docs round,
        # the re-check of carried findings) was counted as strong-tier spend
        from unittest import mock
        cheap, strong = U.MODELS["haiku"], "strong-model"
        # self-review CR-696d3f81: pin the cheap tier, so an ambient CRUCIBLE_VERIFY_CHEAP can't change the result
        with mock.patch.dict(os.environ, {"CRUCIBLE_VERIFY_CHEAP": cheap}):
            self.assertEqual([V.verify_kind(m, i, [cheap, strong]) for i, m in enumerate([cheap, strong])],
                             ["verify_cheap", "verify"])
            self.assertEqual(V.verify_kind(cheap, 0, [cheap]), "verify_cheap")
            self.assertEqual(V.verify_kind(strong, 0, [strong]), "verify")
            # CR-95987648: --no-tiers with the strong verifier set to the cheap model is still cheap-tier spend
            self.assertEqual([V.verify_kind(m, 0, V.verify_tiers(cheap, no_tiers=True)) for m in V.verify_tiers(cheap, True)],
                             ["verify_cheap"])
        with mock.patch.dict(os.environ, {"CRUCIBLE_VERIFY_CHEAP": "none"}):
            self.assertEqual(V.verify_kind(cheap, 0, [cheap]), "verify")      # tiering off: one strong tier

    def test_verify_tiered_labels_salvage_tiers_and_cache_hits(self):
        # self-review CR-eb6a290e / CR-32bc6c82: the labels are set at the call sites, so test them there
        from unittest import mock
        cheap, strong = U.MODELS["haiku"], "strong-model"

        def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
            budget.meter({model: {"input": 1, "output": 1, "cache_read": 0, "cache_creation": 5}}, kind, bool(tools), 0.01)
            if model == cheap and tools:
                raise U.NoStructuredOutput("prose", "the claim holds, I think")
            if not tools:                                          # the salvage transcription
                return {"keep": True, "severity": "medium", "method": "read", "actions": "", "evidence": "",
                        "confidence": "low"}, 0.0
            return {"keep": True, "severity": "medium", "method": "read", "actions": "a", "evidence": "e",
                    "confidence": "high"}, 0.01
        f = {"id": "CR-1", "file": "a.js", "line": 1, "severity": "medium", "title": "t", "problem": "p", "wrong_if": "w",
             "fix": "x", "caused_by_this_change": True, "reachable_in_real_use": True}
        old = V.claude
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"CRUCIBLE_CACHE": d, "CRUCIBLE_VERIFY_CHEAP": cheap}):
            V.claude = fake
            try:
                b = U.Budget(None)
                V.verify_tiered(f, "code", d, b, [cheap, strong])
                k = b.kind_snapshot()
                self.assertEqual({n: (v["calls"], v["no_tools"]) for n, v in k.items()},
                                 {"verify_cheap": (1, False), "salvage": (1, True), "verify": (1, False)})
                # again: the salvaged cheap verdict is not cached (the real verifier is retried), the strong one is
                b = U.Budget(None)
                V.verify_tiered(f, "code", d, b, [cheap, strong])
                k = b.kind_snapshot()
                self.assertEqual((k["verify"]["calls"], k["verify"]["cached_calls"]), (0, 1))
                self.assertEqual((k["verify_cheap"]["calls"], k["salvage"]["calls"]), (1, 1))
                # the cheap tier alone (re-check of a carried finding) is cheap-tier spend
                b = U.Budget(None)
                V.verify_tiered(dict(f, title="other"), "code", d, b, [cheap])
                self.assertEqual(sorted(b.kind_snapshot()), ["salvage", "verify_cheap"])
            finally:
                V.claude = old

    def test_stats_by_call_kind(self):
        from crucible import stats as ST
        f = TestStats._f

        def tok(total):
            return {"total": total, "input": total, "output": 0, "cache_read": 0, "cache_creation": 0,
                    "by_model": {}, "unmetered_calls": 0}

        def kind(calls, cost, write, read, no_tools=False):
            return {"calls": calls, "no_tools": no_tools, "cost_usd": cost, "unmetered_calls": 0, "cached_calls": 0,
                    "input": 0, "output": 0, "cache_read": read, "cache_creation": write}
        with tempfile.TemporaryDirectory() as root:
            for sha in ("s1", "s2", "s3"):
                TestStats._store(root, "o__p", sha, [f("CR-" + sha, sha)])
                p = os.path.join(root, "o__p", sha, "review.json")
                rev = U.read_json(p)
                rev.update(tokens_review=tok(10), tokens_verify=tok(10))
                if sha != "s3":                         # s3 was metered before per-kind metering
                    rev["tokens_by_kind"] = {"review": kind(2, 0.5, 100, 900),
                                             "salvage": kind(1, 0.01, 50, 0, no_tools=True)}
                U.write_json(p, rev)
            t = ST.tokens(ST.collect(root))
            self.assertEqual(t["by_kind_reviews"], 2)
            self.assertEqual(t["by_kind"]["review"]["cache_read"], 1800)
            self.assertEqual((t["by_kind"]["salvage"]["calls"], t["by_kind"]["salvage"]["no_tools"]), (2, True))
            text = ST.report(ST.collect(root))
            self.assertIn("By call kind (2 of 3 metered reviews): review 4 calls $1.00, cache write 200 / read 1,800; "
                          "salvage (no tools) 2 calls $0.02, cache write 100 / read 0.", text)
            self.assertEqual(json.loads(ST.to_json(ST.collect(root)))["tokens"]["by_kind"]["review"]["calls"], 4)
            # self-review CR-d3bb9ba2: the rows in --json carry by_kind too, rounded like every other cost
            for sha, c in (("s1", 0.1), ("s2", 0.2)):
                p = os.path.join(root, "o__p", sha, "review.json")
                rev = U.read_json(p); rev["tokens_by_kind"]["review"]["cost_usd"] = c; U.write_json(p, rev)
            self.assertEqual(json.loads(ST.to_json(ST.collect(root)))["overall"]["by_kind"]["review"]["cost_usd"], 0.3)
            # no review with the field: no line at all, rather than a row of zeros
            for sha in ("s1", "s2"):
                p = os.path.join(root, "o__p", sha, "review.json")
                rev = U.read_json(p); rev.pop("tokens_by_kind"); U.write_json(p, rev)
            self.assertNotIn("By call kind", ST.report(ST.collect(root)))

    def test_cache_hits_are_counted(self):
        # self-review CR-ce3e4b57: a hit makes no call, and the review that paid for it may be gone (a --force re-run
        # overwrites the same commit's review.json), so a review with hits looked fully metered at too few tokens
        old = os.environ.get("CRUCIBLE_CACHE")
        with tempfile.TemporaryDirectory() as d:
            os.environ["CRUCIBLE_CACHE"] = d
            try:
                b = U.Budget(None)
                V.cache_put("k", {"keep": True})
                self.assertEqual(V.cache_hit("k", b), {"keep": True})
                self.assertIsNone(V.cache_hit("missing", b))
                self.assertEqual(b.token_snapshot(), ({}, 0, 1))
            finally:
                if old is None:
                    os.environ.pop("CRUCIBLE_CACHE", None)
                else:
                    os.environ["CRUCIBLE_CACHE"] = old

    def test_stats_tokens_per_held_up_on_metered_reviews_only(self):
        from crucible import stats as ST
        f = TestStats._f

        def tok(total, unm=0):
            return {"total": total, "input": total, "output": 0, "cache_read": 0, "cache_creation": 0,
                    "by_model": {}, "unmetered_calls": unm}
        with tempfile.TemporaryDirectory() as root:
            # legacy review: a held-up finding but no tokens; it must not dilute the ratio
            TestStats._store(root, "o__p", "s0", [f("CR-0", "old")], answers={"CR-0": {"disposition": "fixed", "at": "1"}})
            self.assertIn("Tokens: not recorded", ST.report(ST.collect(root)))
            self.assertEqual(json.loads(ST.to_json(ST.collect(root)))["tokens"], {"answered": False, "reason": "not recorded"})
            TestStats._store(root, "o__p", "s1", [f("CR-1", "a"), f("CR-2", "b"), f("CR-3", "c")],
                             answers={"CR-1": {"disposition": "fixed", "at": "1"}, "CR-2": {"disposition": "refuted", "at": "1"}})
            for sha, t in (("s1", (9000, 1000)), ("s2", (1000, 1000)), ("s3", (5000, 0)), ("s4", (0, 0))):
                if sha != "s1":
                    TestStats._store(root, "o__p", sha, [f("CR-4" + sha, "d" + sha)],
                                     answers={"CR-4s2": {"disposition": "deferred", "at": "1"}} if sha == "s2" else None)
                p = os.path.join(root, "o__p", sha, "review.json")
                rev = U.read_json(p)
                rev.update(tokens_review=tok(t[0]), tokens_verify=tok(t[1], unm=1 if sha == "s3" else 0))
                if sha == "s4":                       # a --force re-run served from the cache
                    rev["tokens_review"]["cached_calls"] = 1
                U.write_json(p, rev)
            s = ST.collect(root)
            t = ST.tokens(s)
            # s0 has no tokens, s3 had an unmetered call, s4 a cache hit: 2 of 5 metered, 12,000 tokens,
            # held up CR-1 + CR-4s2
            self.assertEqual((t["metered_reviews"], t["reviews"], t["total"], t["review"], t["verify"]), (2, 5, 12000, 10000, 2000))
            self.assertEqual((t["per_review"], t["held_up"], t["per_held_up"]), (6000, {"held": 2, "answered": 3}, 6000))
            self.assertEqual(ST.held_up(s["overall"]), (3, 4))      # the overall precision still counts every review
            text = ST.report(s)
            self.assertIn("Tokens (2 of 5 reviews metered): 6,000 per review", text)
            self.assertIn("Tokens per held-up finding: 6,000 (2/3 held up in the metered reviews", text)
            self.assertIn("too few to quote", text)
            self.assertEqual(json.loads(ST.to_json(s))["tokens"]["per_held_up"], 6000)
            self.assertEqual(ST.collect(root, project="o/q")["metered"]["metered_reviews"], 0)

    def test_run_review_stores_tokens(self):
        with tempfile.TemporaryDirectory() as d:
            repo, home = os.path.join(d, "r"), os.path.join(d, "home")
            os.makedirs(os.path.join(repo, "src"))
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                       GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
            g = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env)
            open(os.path.join(repo, "src/a.js"), "w").write("export const a = 1;\n")
            g("init", "-q", "-b", "main"); g("add", "-A"); g("commit", "-qm", "base"); g("checkout", "-qb", "x")
            open(os.path.join(repo, "src/a.js"), "w").write("export const a = 1;\nexport const f = xs => xs[xs.length];\n")
            g("commit", "-qam", "f")

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500, kind="other"):
                review = "findings" in schema["properties"]
                budget.add(0.01)
                budget.meter({model: {"input": 100 if review else 7, "output": 10, "cache_read": 0, "cache_creation": 0}},
                             kind, bool(tools), 0.01)
                if review:
                    return {"summary": "s", "findings": [
                        {"severity": "medium", "file": "src/a.js", "line": 2, "title": "f reads past the end",
                         "problem": "p", "caused_by_this_change": True, "reachable_in_real_use": True,
                         "wrong_if": "w", "fix": "x"}]}, 0.01
                return {"keep": True, "severity": "medium", "method": "read", "actions": "a", "evidence": "e",
                        "confidence": "high"}, 0.01

            olds = (V.HOME, U.HOME, V.claude, os.environ.get("CRUCIBLE_CACHE"))
            V.HOME = U.HOME = home
            os.environ["CRUCIBLE_CACHE"] = os.path.join(home, "cache")
            V.claude = fake
            try:
                out = V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None)
                rev = U.read_json(os.path.join(out, "review.json"))
                self.assertEqual(rev["status"], "done", rev.get("reason"))
                self.assertEqual(rev["tokens_review"]["total"], 110)
                self.assertEqual(rev["tokens_verify"]["total"], 17)   # one confident cheap-tier verdict, no escalation
                kinds = rev["tokens_by_kind"]
                self.assertEqual(sorted(kinds), ["review", "verify_cheap"])
                self.assertEqual((kinds["review"]["calls"], kinds["review"]["input"], kinds["review"]["cost_usd"]),
                                 (1, 100, 0.01))
                self.assertEqual((kinds["verify_cheap"]["calls"], kinds["verify_cheap"]["no_tools"]), (1, False))
                self.assertEqual(rev["tokens_review"]["unmetered_calls"] + rev["tokens_verify"]["unmetered_calls"], 0)
                self.assertIn("tokens (review 110, verify", V.report(rev, {}))
                from crucible import stats as ST
                self.assertTrue(ST.metered(rev))
                # a forced re-run of the same commit is served from the cache and overwrites the review that paid:
                # 0 tokens, so it must not count as metered
                out = V.run_review(repo, "main", force=True, offline=True, skip_checks=True, log=lambda *_: None)
                rev = U.read_json(os.path.join(out, "review.json"))
                self.assertEqual(rev["status"], "done", rev.get("reason"))
                self.assertEqual((rev["tokens_review"]["total"], rev["tokens_verify"]["total"]), (0, 0))
                self.assertEqual((rev["tokens_review"]["cached_calls"], rev["tokens_verify"]["cached_calls"]), (1, 1))
                self.assertFalse(ST.metered(rev))
                self.assertIn("2 served from cache", V.report(rev, {}))
            finally:
                V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
                if olds[3] is None:
                    os.environ.pop("CRUCIBLE_CACHE", None)
                else:
                    os.environ["CRUCIBLE_CACHE"] = olds[3]


class TestModelReplay(unittest.TestCase):
    """`crucible model-replay`: reviewer models re-review stored full rounds, scored by the author's answers."""
    L = {"id": "CR-a", "file": "a.py", "line": 10, "severity": "medium", "source": "review",
         "title": "Cache key ignores the draft", "wrong_if": "the key includes the draft hash"}

    def _store(self, root, repo, sha, rev, answers=None, mtime=None):
        d = os.path.join(root, repo, sha)
        os.makedirs(d)
        U.write_json(os.path.join(d, "review.json"), dict({"repo": repo, "sha": sha, "base": "b" + sha, "status": "done",
                                                           "review_model": "claude-opus-5-5", "findings": [],
                                                           "coverage": {"complete": True}}, **rev))
        if answers is not None:
            p = os.path.join(d, "answers.json")
            U.write_json(p, answers)
            if mtime:
                os.utime(p, (mtime, mtime))

    def test_match_needs_same_file_and_nearby_line_or_shared_wording(self):
        from crucible import modelreplay as M
        reworded = dict(self.L, line=12, title="Draft edits don't invalidate the verdict", wrong_if="x")
        far_same_words = dict(self.L, line=22)
        far_other_words = dict(self.L, line=22, title="Unrelated thing", wrong_if="nothing alike")
        self.assertIsNotNone(M.score(self.L, reworded))           # within LINE_NEAR: wording may differ
        self.assertIsNotNone(M.score(self.L, far_same_words))     # beyond it, the wording has to overlap
        self.assertIsNone(M.score(self.L, far_other_words))
        self.assertIsNone(M.score(self.L, dict(self.L, file="b.py")))
        self.assertIsNone(M.score(self.L, dict(self.L, line=10 + M.LINE_FAR + 1)))
        # one-to-one, the best pair first: the exact copy takes the label, the reworded one is left unmatched
        self.assertEqual(M.match([self.L], [reworded, dict(self.L)]), {0: 1})
        self.assertEqual(M.match([self.L, dict(self.L, line=40, title="Other")], [dict(self.L)]), {0: 0})

    def test_rounds_label_full_rounds_by_answers_from_any_round_of_the_repo(self):
        from crucible import modelreplay as M
        draft_f = dict(self.L, id="CR-d", file="PR_DRAFT.md")
        other = dict(self.L, id="CR-u", title="Never answered")
        with tempfile.TemporaryDirectory() as root:
            # the full round raised CR-a; the author answered it on the later incremental round
            self._store(root, "o__p", "s1", {"started": "2026-11-05", "findings": [self.L, draft_f, other],
                                             "inputs": {"draft": "/w/PR_DRAFT.md"}}, {}, mtime=1000)
            self._store(root, "o__p", "s2", {"started": "2026-11-06", "findings": [self.L],
                                             "incremental": {"from": "s1"}},
                        {"CR-a": {"disposition": "fixed"}, "CR-d": {"disposition": "refuted"}}, mtime=2000)
            self._store(root, "o__q", "q1", {"started": "2026-11-07", "findings": [self.L], "review_model": "claude-sonnet-5-5"},
                        {"CR-a": {"disposition": "refuted"}})
            self._store(root, "JROtto5__crucible", "c1", {"started": "2026-11-08", "findings": [self.L]},
                        {"CR-a": {"disposition": "refuted"}})
            self._store(root, "o__p", "s0", {"started": "2026-11-04", "findings": [self.L], "coverage": {"complete": False}})
            self._store(root, "o__p", "s9", {"started": "2026-11-03", "findings": [self.L], "coverage": None})
            # incomplete but with nothing answered: not a candidate either way, so not counted
            self._store(root, "o__p", "s8", {"started": "2026-11-02", "findings": [other], "coverage": None})
            sk = {}
            got = M.rounds(root, "claude-opus-5-5", skipped=sk)
            self.assertEqual(sk, {M.INCOMPLETE: 2})
            # incremental, sonnet-reviewed, incomplete and self rounds are left out
            self.assertEqual([(r["repo"], r["sha"]) for r in got], [("o__p", "s1")])
            self.assertEqual([(f["id"], f["disposition"]) for f in got[0]["labelled"]], [("CR-a", "fixed")])  # draft out
            self.assertEqual([r["sha"] for r in M.rounds(root, "claude-opus-5-5", include_self=True)], ["c1", "s1"])
            # a later answer to the same id wins
            self._store(root, "o__p", "s3", {"started": "2026-11-09", "findings": [], "incremental": {"from": "s2"}},
                        {"CR-a": {"disposition": "refuted"}}, mtime=3000)
            self.assertEqual(M.rounds(root, "claude-opus-5-5")[0]["labelled"][0]["disposition"], "refuted")

    def test_pick_takes_each_projects_newest_in_turn(self):
        from crucible import modelreplay as M
        c = [{"repo": r, "started": t} for r, t in (("a", "9"), ("a", "8"), ("a", "7"), ("b", "6"), ("c", "5"))]
        self.assertEqual([(r["repo"], r["started"]) for r in M.pick(c, 4)], [("a", "9"), ("b", "6"), ("c", "5"), ("a", "8")])

    def test_score_arm_counts_raw_and_kept_and_lists_the_rest(self):
        from crucible import modelreplay as M
        held = dict(self.L, disposition="fixed")
        refuted = dict(self.L, id="CR-r", file="b.py", title="Leaks a handle", disposition="refuted")
        missed = dict(self.L, id="CR-m", file="c.py", title="Missing await", disposition="deferred")
        r = {"labelled": [held, refuted, missed], "inputs": {"draft": "/w/PR_DRAFT.md"}}
        review = {"findings": [dict(self.L, title="Draft change keeps old verdict"), dict(self.L, file="z.py", title="New"),
                               dict(self.L, file="PR_DRAFT.md", title="Too long")],
                  "dropped": [dict(refuted)], "cost_usd": 0.5,
                  "tokens_review": {"total": 100}, "tokens_verify": {"total": 20}}
        s = M.score_arm(r, review)
        self.assertEqual((s["held"], s["refuted"], s["found_held"], s["kept_held"]), (2, 1, 1, 1))
        self.assertEqual((s["found_refuted"], s["kept_refuted"]), (1, 0))      # raised, then dropped by verification
        self.assertEqual((s["kept"], s["raw"], s["tokens"]), (2, 3, 120))      # the draft finding isn't counted
        self.assertEqual([f["file"] for f in s["unlabelled"]], ["z.py"])
        self.assertEqual([f["id"] for f in s["missed_held"]], ["CR-m"])
        rows = [dict(r, repo="o__p", sha="s" * 12, arms={"claude-opus-5-5": s, "claude-sonnet-5-5": s})]
        out = M.report(rows, {"an arm failed": 1}, ["claude-opus-5-5", "claude-sonnet-5-5"])
        self.assertIn("held-up findings re-found 1/2 raw, kept 1/2", out)
        self.assertIn("$ per held-up finding kept $0.50", out)
        self.assertIn("skipped 1: an arm failed", out)
        self.assertIn("c.py:10 [medium] Missing await", out)

    def test_run_arm_reviews_a_throwaway_checkout_read_only_in_a_throwaway_home(self):
        from crucible import modelreplay as M
        with tempfile.TemporaryDirectory() as tmp:
            clone = os.path.join(tmp, "clone")
            os.makedirs(clone)
            for cmd in (["init", "-q"], ["remote", "add", "upstream", "https://github.com/o/p.git"]):
                U.git(clone, *cmd)
            with open(os.path.join(clone, "a.py"), "w") as fh:
                fh.write("x = 1\n")
            U.git(clone, "add", "a.py")
            U.git(clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
            sha = U.git(clone, "rev-parse", "HEAD").strip()
            proj = os.path.join(U.HOME, "projects", "o__p")
            os.makedirs(proj, exist_ok=True)
            with open(os.path.join(proj, "rules.md"), "w") as fh:
                fh.write("learned")
            seen = {}

            def fake_run(cmd, *a, env=None, **kw):
                if "crucible" not in cmd:                              # git calls go through
                    return real(cmd, *a, env=env, **kw)
                seen.update(cmd=cmd, env=env)
                tree = cmd[cmd.index("review") + 1]
                seen["key"] = U.project_key(tree)
                seen["rules"] = os.path.exists(os.path.join(env["CRUCIBLE_HOME"], "projects", "o__p", "rules.md"))
                d = os.path.join(env["CRUCIBLE_HOME"], "reviews", "o__p", sha)
                os.makedirs(d)
                U.write_json(os.path.join(d, "review.json"), {"status": seen.get("status", "done"), "findings": [],
                                                              "coverage": {"complete": True},
                                                              "review_model": seen.get("ran", env["CRUCIBLE_REVIEW_MODEL"])})
                return subprocess.CompletedProcess(cmd, 1, "", "")

            r = {"repo": "o__p", "sha": sha, "base": sha, "inputs": {"draft": "/gone/PR_DRAFT.md", "draft_sha": "x"}}
            real = M.subprocess.run
            M.subprocess.run = fake_run
            try:
                os.environ["CRUCIBLE_VERIFY_MODEL"] = "pinned"
                os.environ["CRUCIBLE_ROUTE"] = "1"
                rev = M.run_arm(clone, r, "claude-sonnet-5-5", os.path.join(tmp, "w"))
                self.assertEqual(rev["status"], "done")
                for flag in ("--no-exec", "--offline", "--full", "--fresh", "--force"):
                    self.assertIn(flag, seen["cmd"])
                self.assertNotIn("--draft", seen["cmd"])                # the stored draft is gone
                self.assertEqual(seen["env"]["CRUCIBLE_REVIEW_MODEL"], "claude-sonnet-5-5")
                self.assertNotIn("CRUCIBLE_VERIFY_MODEL", seen["env"])  # the arm's own verifier pick
                self.assertNotIn("CRUCIBLE_ROUTE", seen["env"])         # routing could swap the reviewer
                self.assertNotEqual(seen["env"]["CRUCIBLE_HOME"], U.HOME)
                self.assertEqual(seen["key"], "o__p")                   # so the learned rules apply
                self.assertTrue(seen["rules"])
                seen["ran"] = "claude-sonnet-5-5"                        # e.g. routed to another reviewer
                with self.assertRaises(U.Failed):
                    M.run_arm(clone, r, "claude-opus-5-5", os.path.join(tmp, "w3"))
                seen.pop("ran")
                seen["status"] = "running"
                with self.assertRaises(U.Failed):
                    M.run_arm(clone, r, "claude-opus-5-5", os.path.join(tmp, "w2"))
                # a partial clone whose origin is a fork: checkout() copies that origin, upstream must still win
                U.git(clone, "remote", "add", "origin", "https://github.com/me/p.git")
                U.git(clone, "config", "remote.origin.promisor", "true")
                tree, home = M._prepare(clone, r, os.path.join(tmp, "w4"), "a/b")
                self.assertEqual(U.project_key(tree), "o__p")
                self.assertEqual(os.path.dirname(tree), os.path.join(tmp, "w4"))   # "a/b" didn't nest a directory
                with self.assertRaises(U.Failed):                                 # wrong project: fail before paying
                    M._prepare(clone, dict(r, repo="x__y"), os.path.join(tmp, "w5"), "opus")
            finally:
                M.subprocess.run = real
                os.environ.pop("CRUCIBLE_VERIFY_MODEL", None)
                os.environ.pop("CRUCIBLE_ROUTE", None)
                shutil.rmtree(proj, ignore_errors=True)
            self.assertFalse(os.path.exists(os.path.join(U.HOME, "reviews", "o__p")))

    def test_report_takes_any_model_id_and_counts_a_repeated_arm_once(self):
        from crucible import modelreplay as M
        a = M.score_arm({"labelled": [dict(self.L, disposition="fixed")], "inputs": {}}, {"findings": [dict(self.L)]})
        rows = [{"repo": "o__p", "sha": "s" * 12, "arms": {"claude-opus-5-5": a, "nodash": a}}]
        out = M.report(rows, {}, ["claude-opus-5-5", "nodash", "nodash"])
        self.assertIn("opus 1/0/0", out)
        self.assertIn("nodash 1/0/0", out)
        self.assertEqual(out.count("- review nodash: held-up findings re-found 1/1 raw"), 1)
        self.assertIn("favours it", out)                         # the label bias is stated in the report

    def test_draft_is_passed_only_while_its_text_has_the_stored_hash(self):
        from crucible import modelreplay as M
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "PR_DRAFT.md")
            with open(path, "w") as fh:
                fh.write("Fixes #3.\n")
            want = hashlib.sha256(R.submitted_text("Fixes #3.\n").encode()).hexdigest()[:16]
            self.assertEqual(M.draft_still_matches({"inputs": {"draft": path, "draft_sha": want}}), path)
            self.assertIsNone(M.draft_still_matches({"inputs": {"draft": path, "draft_sha": "0" * 16}}))

    def test_run_pairs_arms_and_leaves_out_a_round_any_arm_failed(self):
        from crucible import modelreplay as M
        rounds = [{"repo": r, "sha": s, "base": "b", "started": t, "inputs": {}, "labelled": [dict(self.L, disposition="fixed")]}
                  for r, s, t in (("o__a", "a1", "3"), ("o__b", "b1", "2"), ("o__c", "c1", "1"))]
        calls = []

        def fake_arm(clone, r, model, tmp, budget=None, log=None):
            calls.append((r["sha"], model))
            if r["sha"] == "b1" and model == "claude-sonnet-5-5":
                raise U.Failed("review incomplete")
            return {"findings": [dict(self.L)], "cost_usd": 0.1}

        saved = (M.rounds, M.anchoring.find_clones, M.anchoring.has_commit, M.run_arm)
        def fake_rounds(root, model, inc=False, skipped=None):
            skipped[M.INCOMPLETE] = 2
            return rounds
        M.rounds = fake_rounds
        M.anchoring.find_clones = lambda dirs: ["/clone"]
        M.anchoring.has_commit = lambda c, sha: sha != "c1"
        M.run_arm = fake_arm
        shutil.rmtree(M.ARMS, ignore_errors=True)
        try:
            rows, skipped, _ = M.run("/r", ["/c"], ["claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5-5"], n=5,
                                     log=lambda m: None)
        finally:
            M.rounds, M.anchoring.find_clones, M.anchoring.has_commit, M.run_arm = saved
            shutil.rmtree(M.ARMS, ignore_errors=True)
        self.assertEqual([r["sha"] for r in rows], ["a1"])
        self.assertEqual(sorted(rows[0]["arms"]), ["claude-opus-5-5", "claude-sonnet-5-5"])
        self.assertEqual(skipped, {"no local clone has the commit and its base": 1, "an arm failed": 1,
                                   "excluded (--exclude)": 0, M.INCOMPLETE: 2})
        self.assertIn("skipped 2: stored round's coverage incomplete", M.report(rows, skipped, ["claude-opus-5-5"]))
        self.assertEqual(sum(1 for sha, m in calls if sha == "a1"), 2)      # the repeated opus arm ran once

    def test_run_reuses_kept_arms_so_a_bigger_sample_pays_only_for_new_rounds(self):
        from crucible import modelreplay as M
        mk = lambda repo, sha, t: {"repo": repo, "sha": sha, "base": "b" + sha, "started": t, "inputs": {},
                                   "labelled": [dict(self.L, disposition="fixed")]}
        stored = [mk("o__a", "a1", "3"), mk("o__b", "b1", "2")]
        calls = []

        def fake_arm(clone, r, model, tmp, budget=None, log=None):
            calls.append((r["sha"], model))
            if r["sha"] == "c1" and model == "claude-sonnet-5-5":
                raise U.Failed("usage limit")
            return {"findings": [dict(self.L)], "cost_usd": 0.25, "review_model": model}

        saved = (M.rounds, M.anchoring.find_clones, M.anchoring.has_commit, M.run_arm, M.pipeline_version)
        M.rounds = lambda root, model, inc=False, skipped=None: list(stored)
        M.anchoring.find_clones = lambda dirs: ["/clone"]
        M.anchoring.has_commit = lambda c, sha: True
        M.run_arm = fake_arm
        models = ["claude-opus-5-5", "claude-sonnet-5-5"]
        go = lambda n, **kw: M.run("/r", ["/c"], models, n=n, budget=0.8, log=lambda m: None, **kw)
        shutil.rmtree(M.ARMS, ignore_errors=True)
        try:
            rows, _, spent = go(1)
            self.assertEqual([r["sha"] for r in rows], ["a1"])
            self.assertEqual((len(calls), spent), (2, 0.5))
            # a newer round lands; the next, bigger run keeps a1 (both arms kept), runs only what it adds
            stored.insert(0, mk("o__c", "c1", "4"))
            calls.clear()
            rows, skipped, spent = go(3)
            self.assertEqual([r["sha"] for r in rows], ["a1", "b1"])            # c1's sonnet arm failed
            self.assertNotIn(("a1", "claude-opus-5-5"), calls)
            self.assertEqual(sorted(calls), sorted([("c1", "claude-opus-5-5"), ("c1", "claude-sonnet-5-5"),
                                                    ("b1", "claude-opus-5-5"), ("b1", "claude-sonnet-5-5")]))
            self.assertTrue(all(a["reused"] for a in rows[0]["arms"].values()))
            self.assertFalse(any(a["reused"] for a in rows[1]["arms"].values()))
            out = M.report(rows, skipped, models, spent)
            self.assertIn("2 of 4 arms reused from an earlier run", out)
            # c1's opus arm was paid for though its round was left out: b1 $0.50 + c1 opus $0.25
            self.assertIn("this run spent $0.75 on the arms it ran", out)
            # c1's opus arm was kept; the retry runs only sonnet
            calls.clear()
            M.run_arm = lambda clone, r, model, tmp, budget=None, log=None: (
                calls.append((r["sha"], model)) or {"findings": [], "cost_usd": 0.1, "review_model": model})
            rows, _, _ = go(3)
            self.assertEqual(calls, [("c1", "claude-sonnet-5-5")])
            self.assertEqual(len(rows), 3)
            # another budget is another run: nothing reused
            calls.clear()
            M.run("/r", ["/c"], models, n=1, budget=2.0, log=lambda m: None)
            self.assertEqual(len(calls), 2)
            # a changed review pipeline (a prompt edit) doesn't reuse arms made by the old one
            calls.clear()
            M.pipeline_version = lambda: "other"
            go(1)
            self.assertEqual(len(calls), 2)
            M.pipeline_version = saved[4]
            # nor does a changed prompt input of the project (learned rules, STYLE.md, memory, style.json)
            go(3)                                        # c1 was re-run under "other": settle it on the real version
            proj = os.path.join(U.HOME, "projects", "o__a")
            os.makedirs(proj, exist_ok=True)
            try:
                for f in M.PROJECT_INPUTS:
                    with open(os.path.join(proj, f), "w") as fh:
                        fh.write("new " + f)
                    calls.clear()
                    go(3)
                    self.assertEqual(sorted(calls), [("a1", "claude-opus-5-5"), ("a1", "claude-sonnet-5-5")], f)
                # files every review or waiver rewrites aren't prompt inputs: they don't cost the kept arms
                for f in ("branches.json", "waivers.json", "meta.json"):
                    U.write_json(os.path.join(proj, f), {"touched": f})
                calls.clear()
                go(3)
                self.assertEqual(calls, [])
            finally:
                shutil.rmtree(proj, ignore_errors=True)
            # --fresh re-runs; --exclude leaves a round out and counts it
            calls.clear()
            rows, skipped, _ = go(3, fresh=True, exclude=("a1",))
            self.assertEqual(sorted({s for s, _ in calls}), ["b1", "c1"])
            self.assertEqual(skipped["excluded (--exclude)"], 1)
            self.assertNotIn("reused", M.report(rows, skipped, models))
        finally:
            M.rounds, M.anchoring.find_clones, M.anchoring.has_commit, M.run_arm, M.pipeline_version = saved
            shutil.rmtree(M.ARMS, ignore_errors=True)
        self.assertTrue(M.ARMS.startswith(U.HOME))                          # never the real ~/.crucible in tests

    def test_pick_prefers_replayed_rounds_but_keeps_one_project_at_a_time(self):
        from crucible import modelreplay as M
        c = [{"repo": r, "sha": s, "started": t}
             for r, s, t in (("A", "a1", "9"), ("A", "a2", "8"), ("B", "b1", "7"), ("C", "c1", "6"), ("A", "a3", "5"),
                             ("D", "d1", "4"))]
        got = lambda n, prefer: [r["sha"] for r in M.pick(c, n, prefer)]
        # all replayed: the same balanced sample as without a cache, not the newest three (a1, a2, b1)
        every = {(r["repo"], r["sha"]) for r in c}
        self.assertEqual(got(3, every), ["a1", "b1", "c1"])
        # an older replayed round wins within its project, and projects with one come first
        self.assertEqual(got(2, {("A", "a3"), ("D", "d1")}), ["a3", "d1"])
        self.assertEqual(got(4, {("D", "d1")}), ["d1", "a1", "b1", "c1"])

    def test_pipeline_version_follows_what_review_runs(self):
        from crucible import modelreplay as M
        real = os.path.dirname(M.__file__)
        with tempfile.TemporaryDirectory() as tmp:
            pkg = os.path.join(tmp, "crucible")
            shutil.copytree(real, pkg, ignore=shutil.ignore_patterns("__pycache__"))
            files = M.pipeline_files(pkg)
            for f in ("review.py", "cli.py", "util.py", "readiness.py", "style.py", "catalog.py"):
                self.assertIn(f, files)
            for f in ("modelreplay.py", "assist.py", "learn.py", "stats.py", "__init__.py"):
                self.assertNotIn(f, files)
            v = M.pipeline_version(pkg)
            self.assertEqual((len(v), v), (16, M.pipeline_version(pkg)))

            def edited(rel, text="\n# edit\n"):
                with open(os.path.join(pkg, rel), "a") as fh:
                    fh.write(text)
                return M.pipeline_version(pkg)
            self.assertEqual(edited("modelreplay.py"), v)          # the replay, polish/prep and stats: arms stay
            self.assertEqual(edited("assist.py"), v)
            self.assertEqual(edited("stats.py"), v)
            v2 = edited("review.py")                              # a prompt edit
            self.assertNotEqual(v2, v)
            guide = sorted(os.listdir(os.path.join(pkg, "guides")))[0]
            v3 = edited(os.path.join("guides", guide))
            self.assertNotEqual(v3, v2)
            # a module review starts importing (lazily, indented) joins the hash
            self.assertEqual(edited("learn.py"), v3)
            v4 = edited("review.py", "\ndef _late():\n    from . import learn\n")
            self.assertIn("learn.py", M.pipeline_files(pkg))
            self.assertNotEqual(edited("learn.py"), v4)
            # a parenthesised name list over several lines, with a comment
            self.assertNotIn("assist.py", M.pipeline_files(pkg))
            edited("review.py", "\nfrom . import (\n    diff,  # x\n    assist as a,\n)\n")
            self.assertIn("assist.py", M.pipeline_files(pkg))

    def test_a_billed_arm_that_is_rejected_still_counts_in_spend(self):
        from crucible import modelreplay as M
        saved = (M._prepare, M.subprocess.run, M.read_json)
        M._prepare = lambda clone, r, tmp, label: ("/tree", "/home")
        M.subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "")
        M.read_json = lambda p, d=None: {"status": "done", "findings": [], "coverage": {"complete": False},
                                         "review_model": "nodash", "cost_usd": 0.4}
        try:
            with self.assertRaises(U.Failed) as cm:
                M.run_arm("/c", {"repo": "o__p", "sha": "s" * 12, "base": "b", "inputs": {}}, "nodash", "/t")
            self.assertEqual(cm.exception.cost, 0.4)
        finally:
            M._prepare, M.subprocess.run, M.read_json = saved
        rnd = {"repo": "o__p", "sha": "s1", "base": "b", "started": "1", "inputs": {},
               "labelled": [dict(self.L, disposition="fixed")]}

        def billed_then_rejected(clone, r, model, tmp, budget=None, log=None):
            ex = U.Failed("review incomplete")
            ex.cost = 0.4
            raise ex
        saved = (M.rounds, M.anchoring.find_clones, M.anchoring.has_commit, M.run_arm)
        M.rounds = lambda root, model, inc=False, skipped=None: [rnd]
        M.anchoring.find_clones = lambda dirs: ["/clone"]
        M.anchoring.has_commit = lambda c, sha: True
        M.run_arm = billed_then_rejected
        try:
            rows, skipped, spent = M.run("/r", ["/c"], ["nodash"], n=1, fresh=True, log=lambda m: None)
        finally:
            M.rounds, M.anchoring.find_clones, M.anchoring.has_commit, M.run_arm = saved
        self.assertEqual((rows, skipped["an arm failed"], spent), ([], 1, 0.4))

    def test_model_replay_cli_validates_exclude_and_passes_fresh(self):
        from crucible import cli, modelreplay as M
        import argparse, contextlib, io
        self.assertEqual(cli._sha_prefix("ABCDEF0"), "abcdef0")
        for bad in ("a1", "abc123", "zzzzzzz", "a" * 41):
            with self.assertRaises(argparse.ArgumentTypeError):
                cli._sha_prefix(bad)
        seen = {}

        def fake_run(root, clones, models, n, budget, inc, log=None, fresh=False, exclude=()):
            seen.update(fresh=fresh, exclude=exclude, models=models)
            return [], {}, 0.0
        real = M.run
        M.run = fake_run
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                cli.main(["model-replay", "--clones", "/x", "--fresh", "--exclude", "E72B878703", "--models", "opus"])
        finally:
            M.run = real
        self.assertEqual(seen, {"fresh": True, "exclude": ["e72b878703"], "models": ["claude-opus-5-5"]})
        self.assertIn("this run spent $0.00", out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["model-replay", "--clones", "/x", "--exclude", "a1"])

    def test_shape_counts_production_lines_outside_tests_and_docs(self):
        from crucible import modelreplay as M
        with tempfile.TemporaryDirectory() as clone:
            U.git(clone, "init", "-q")

            def commit(files):
                for f, body in files.items():
                    with open(os.path.join(clone, *f.split("/")), "w") as fh:
                        fh.write(body)
                U.git(clone, "add", "-A")
                U.git(clone, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "c")
                return U.git(clone, "rev-parse", "HEAD").strip()
            os.makedirs(os.path.join(clone, "tests"))
            os.makedirs(os.path.join(clone, "src"))
            base = commit({"README.md": "a\n", "src/a.py": "x = 1\n"})
            docs = commit({"README.md": "a\nb\nc\n"})
            self.assertEqual(M.shape(clone, base, docs), {"kind": "docs/PR text", "prod_files": 0, "prod_lines": 0,
                                                          "size": None})
            tests = commit({"tests/test_a.py": "def test(): pass\n" * 80})
            # no production files, so no size bucket: "<=50" would mix it in with small code changes
            self.assertEqual((M.shape(clone, docs, tests)["kind"], M.shape(clone, docs, tests)["size"]), ("tests only", None))
            one = commit({"src/a.py": "x = 2\n", "tests/test_a.py": "t\n" * 300, "src/b b.py": "y\n" * 60})
            got = M.shape(clone, tests, one)
            # 2 lines in a.py (1 out, 1 in) + 60 in "b b.py"; the 300+ test lines don't count
            self.assertEqual((got["kind"], got["prod_files"], got["prod_lines"], got["size"]), ("multi-file", 2, 62, "51-200"))
            single = commit({"src/a.py": "z\n" * 250})
            self.assertEqual((M.shape(clone, one, single)["kind"], M.shape(clone, one, single)["size"]), ("single-file", ">200"))
            self.assertEqual(M.shape(clone, single, single)["kind"], "no files")
            self.assertIsNone(M.shape(clone, "0" * 40, single))      # unreadable diff: no shape, not an empty one

    def test_report_breaks_arms_down_by_change_shape_and_marks_small_buckets(self):
        from crucible import modelreplay as M
        held = dict(self.L, disposition="fixed")
        refuted = dict(self.L, id="CR-r", file="b.py", title="Leaks a handle", disposition="refuted")
        hit = M.score_arm({"labelled": [held], "inputs": {}}, {"findings": [dict(self.L)], "cost_usd": 0.4})
        miss = M.score_arm({"labelled": [held], "inputs": {}}, {"findings": [], "cost_usd": 0.1})
        alarm = M.score_arm({"labelled": [refuted], "inputs": {}}, {"findings": [dict(refuted)], "cost_usd": 0.3})
        mk = lambda sha, kind, lines, size, o, s: {"repo": "o__p", "sha": sha * 12, "arms": {
            "claude-opus-5-5": o, "claude-sonnet-5-5": s},
            "shape": {"kind": kind, "prod_files": 1, "prod_lines": lines, "size": size}}
        rows = [mk("a", "single-file", 12, "<=50", hit, miss), mk("b", "multi-file", 300, ">200", hit, hit),
                mk("c", "single-file", 40, "<=50", alarm, alarm)]
        out = M.report(rows, {}, ["claude-opus-5-5", "claude-sonnet-5-5"])
        self.assertIn("kind single-file: 2 round(s) too few (n=2): opus 1/1, 1/1, $0.70, $0.70; "
                      "sonnet 0/1, 1/1, $0.40, n/a", out)
        self.assertIn("kind multi-file: 1 round(s) too few (n=1): opus 1/1, 0/0, $0.40, $0.40", out)
        self.assertIn("production lines <=50: 2 round(s)", out)
        self.assertNotIn("production lines 51-200", out)          # empty buckets aren't printed
        tests_only = mk("d", "tests only", 0, None, hit, hit)
        out = M.report(rows + [tests_only], {}, ["claude-opus-5-5"])
        self.assertIn("kind tests only: 1 round(s)", out)
        self.assertIn("production lines <=50: 2 round(s)", out)  # the tests-only round has no size row
        self.assertIn("(held 1, refuted 0; multi-file, 300 production lines)", out)
        big = [mk(str(i % 10), "multi-file", 300, ">200", hit, hit) for i in range(M.TOO_FEW)]
        self.assertIn(f"kind multi-file: {M.TOO_FEW} round(s) n={M.TOO_FEW}:", M.report(big, {}, ["claude-opus-5-5"]))
        self.assertNotIn("By change shape", M.report([dict(r, shape=None) for r in rows], {}, ["claude-opus-5-5"]))

    def test_incomplete_review_is_a_failed_arm_not_a_clean_zero(self):
        from crucible import modelreplay as M
        saved = (M._prepare, M.subprocess.run, M.read_json)
        M._prepare = lambda clone, r, tmp, label: ("/tree", "/home")
        M.subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "")
        M.read_json = lambda p, d=None: {"status": "done", "findings": [], "coverage": {"complete": False},
                                         "review_model": "nodash"}
        try:
            with self.assertRaises(U.Failed):
                M.run_arm("/c", {"repo": "o__p", "sha": "s" * 12, "base": "b", "inputs": {}}, "nodash", "/t")
            M.read_json = lambda p, d=None: {"status": "done", "findings": [], "review_model": "nodash"}
            with self.assertRaises(U.Failed):                   # no coverage record: not known to be complete
                M.run_arm("/c", {"repo": "o__p", "sha": "s" * 12, "base": "b", "inputs": {}}, "nodash", "/t")
        finally:
            M._prepare, M.subprocess.run, M.read_json = saved


class TestMigrationOrder(unittest.TestCase):
    """BLAZE escape 2026-11-10: a new migration numbered below one already applied ran out of order on replay."""

    def _files(self, repo):
        return D.parse(sh(repo, "git", "diff", "main...HEAD"))

    def test_lower_version_fails_and_names_both_files(self):
        repo = make_repo({"supabase/migrations/20261101000000_a.sql": "x", "supabase/migrations/20261105000000_b.sql": "y"},
                         {"supabase/migrations/20261103000000_new.sql": "z"})
        r = R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))
        self.assertEqual(r["status"], "fail", r)
        self.assertIn("20261103000000_new.sql", r["evidence"]); self.assertIn("20261105000000_b.sql", r["evidence"])

    def test_newer_version_passes_and_other_layouts(self):
        repo = make_repo({"db/migrate/001_a.rb": "x", "app/migrations/0001_initial.py": "x", "app/migrations/__init__.py": ""},
                         {"db/migrate/002_b.rb": "y", "app/migrations/0002_more.py": "y"})
        r = R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))
        self.assertEqual(r["status"], "pass", r); self.assertIn("2 new migration", r["evidence"])

    def test_reused_version_warns_and_other_widths_are_ignored(self):
        repo = make_repo({"migrations/0003_a.sql": "x", "migrations/20260101000000_old.sql": "x"},
                         {"migrations/0003_b.sql": "y"})
        r = R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))
        self.assertEqual(r["status"], "warn", r); self.assertIn("reuses version 0003", r["evidence"])

    def test_tracking_ref_ahead_of_merge_base_counts(self):
        repo = make_repo({"migrations/V1__init.sql": "x"}, {"migrations/V2__mine.sql": "y"})
        base = sh(repo, "git", "rev-parse", "main")
        sh(repo, "git", "checkout", "-q", "main")
        open(os.path.join(repo, "migrations/V3__theirs.sql"), "w").write("z")
        sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", "upstream")
        sh(repo, "git", "checkout", "-q", "fix")
        files = D.parse(sh(repo, "git", "diff", f"{base}..HEAD"))
        self.assertEqual(R.migration_order(repo, base, files)["status"], "pass")
        r = R.migration_order(repo, base, files, "main")
        self.assertEqual(r["status"], "fail", r); self.assertIn("V3__theirs.sql", r["evidence"])

    def test_no_migration_is_na(self):
        repo = make_repo({"a.py": "x"}, {"b.py": "y", "docs/migrations.md": "z"})
        self.assertEqual(R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))["status"], "na")

    def test_laravel_dates_compare_whole_and_flyway_dotted(self):
        # self-review CR-ff896901: the year alone was the version, so every new Laravel migration "reused" 2026
        repo = make_repo({"database/migrations/2026_11_05_000000_b.php": "x", "db/migration/V1_2__b.sql": "x"},
                         {"database/migrations/2026_11_06_000000_c.php": "y", "db/migration/V1_10__c.sql": "y"})
        r = R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))
        self.assertEqual(r["status"], "pass", r)
        for old, new in (("V1_10__b.sql", "V1_2__new.sql"), ("V2__b.sql", "V1_5__new.sql"), ("V10__b.sql", "V9__new.sql")):
            repo = make_repo({f"db/migration/{old}": "x"}, {f"db/migration/{new}": "y"})   # re-review CR-1a8e7f82
            r = R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))
            self.assertEqual(r["status"], "fail", (old, new, r))
        repo = make_repo({"database/migrations/2026_11_05_000000_b.php": "x"},
                         {"database/migrations/2026_11_03_000000_new.php": "y"})
        r = R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))
        self.assertEqual(r["status"], "fail", r); self.assertIn("2026_11_03_000000", r["evidence"])

    def test_prisma_folder_versions(self):
        repo = make_repo({"prisma/migrations/20261105000000_b/migration.sql": "x"},
                         {"prisma/migrations/20261103000000_new/migration.sql": "y"})
        r = R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))
        self.assertEqual(r["status"], "fail", r); self.assertIn("20261105000000_b", r["evidence"])
        repo = make_repo({"prisma/migrations/20261105000000_b/migration.sql": "x"},
                         {"prisma/migrations/20261106000000_new/migration.sql": "y"})
        self.assertEqual(R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))["status"], "pass")

    def test_padded_equal_versions_and_prisma_reuse_warn(self):
        # re-review CR-b6425b18 / CR-18937888: V1 == V1_0 is a reuse; a numbered note beside Prisma folders isn't one
        for base_files, new in (({"db/migration/V1__a.sql": "x"}, "db/migration/V1_0__b.sql"),
                                ({"prisma/migrations/20261105000000_a/migration.sql": "x"},
                                 "prisma/migrations/20261105000000_b/migration.sql")):
            repo = make_repo(base_files, {new: "y"})
            r = R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))
            self.assertEqual(r["status"], "warn", (new, r)); self.assertIn("reuses version", r["evidence"])
        repo = make_repo({"prisma/migrations/20261201000000_readme.md": "x", "prisma/migrations/20261101000000_a/migration.sql": "x"},
                         {"prisma/migrations/20261105000000_b/migration.sql": "y"})
        self.assertEqual(R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))["status"], "pass")

    def test_numbered_docs_and_notes_are_not_migrations(self):
        # self-review CR-07179453: a numbered guide in docs/migrations/ gave a hard fail
        repo = make_repo({"docs/migrations/0005-v3-notes.md": "x", "scripts/migrate/12_users.txt": "x"},
                         {"docs/migrations/0004-upgrade-guide.md": "y", "scripts/migrate/04_orgs.txt": "y"})
        self.assertEqual(R.migration_order(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))["status"], "na")



class TestSinceNote(unittest.TestCase):
    """DRG-63: an incremental pass labels its diff as the inter-diff and carries the whole change as context."""

    def test_plain_follow_up_commit(self):
        ch = {"files": ["a.py", "b.py"], "text": "x"}
        note = V.since_note("1" * 40, False, ch, {"a.py": "WHOLE-A", "c.py": "WHOLE-C"}, "2" * 40)
        self.assertIn("INTER-DIFF 1111111111..HEAD", note)
        self.assertIn("(2222222222..HEAD)", note)
        self.assertIn("WHOLE-A", note)
        self.assertNotIn("WHOLE-C", note)                   # only this pass's files
        self.assertNotIn("amended", note)

    def test_context_is_capped_and_missing_is_said(self):
        ch = {"files": ["a.py"], "text": "x"}
        note = V.since_note("1" * 40, True, ch, {"a.py": "z" * (V.SINCE_CONTEXT_CHARS + 500)}, "2" * 40)
        self.assertIn("amended or rebased", note)
        self.assertIn("a.py: whole-change diff truncated", note)
        self.assertLess(note.count("z"), V.SINCE_CONTEXT_CHARS + 100)
        self.assertIn("(not available)", V.since_note("1" * 40, False, ch, {}, "2" * 40))

    def test_big_first_file_leaves_room_for_the_next(self):
        ch = {"files": ["big.py", "small.py"], "text": "x"}
        texts = {"big.py": "z" * (V.SINCE_CONTEXT_CHARS * 2), "small.py": "SMALL-WHOLE"}
        note = V.since_note("1" * 40, False, ch, texts, "2" * 40)
        self.assertIn("SMALL-WHOLE", note)
        self.assertIn("big.py: whole-change diff truncated", note)
        self.assertLessEqual(note.count("z"), V.SINCE_CONTEXT_CHARS)

    def test_small_file_whole_and_big_file_gets_the_rest(self):
        ch = {"files": ["big.py", "small.py"], "text": "x"}
        texts = {"big.py": "z" * (V.SINCE_CONTEXT_CHARS * 2), "small.py": "s" * 3000}
        note = V.since_note("1" * 40, False, ch, texts, "2" * 40)
        self.assertEqual(note.count("s" * 3000), 1)
        self.assertEqual(note.count("z"), V.SINCE_CONTEXT_CHARS - 3000)     # not an even 10k split

    def test_many_file_pass_names_files_instead_of_stubs(self):
        # 300 files: an even split would give 66 chars each, plus 300 truncation markers past the cap
        files = [f"pkg/m{i:03d}.py" for i in range(300)]
        texts = {p: "q" * 900 for p in files}
        note = V.since_note("1" * 40, False, {"files": files, "text": "x"}, texts, "2" * 40)
        self.assertLess(len(note), V.SINCE_CONTEXT_CHARS + V.SINCE_NAMES_CHARS + 1500)
        self.assertNotIn("truncated", note)
        self.assertEqual(note.count("q" * 900), V.SINCE_CONTEXT_CHARS // 900)  # whole files while they fit
        self.assertIn(f"whole change not shown for {300 - V.SINCE_CONTEXT_CHARS // 900} file(s)", note)

    def test_split_file_context_goes_with_every_pass(self):
        # every pass is its own model call, so a later pass can't see context sent with an earlier one
        texts = {"big.py": "BIG-WHOLE"}
        for text in ("x", "y"):
            self.assertIn("BIG-WHOLE", V.since_note("1" * 40, False, {"files": ["big.py"], "text": text}, texts, "2" * 40))

    def test_big_catalog_stays_out_of_the_context(self):
        def po(name, n):
            body = "".join(f'+msgid "s{i}"\n+msgstr "t{i}"\n' for i in range(n))
            return (f"diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n"
                    f"@@ -0,0 +1,{2 * n} @@\n{body}")
        files = D.parse(po("fr.po", 150) + po("de.po", 5)
                        + "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n")
        self.assertEqual(sorted(V.since_texts(files, [])), ["a.py", "de.po"])   # 300 lines digest; 10 don't
        self.assertEqual(sorted(V.since_texts(files, ["de.po"])), ["a.py"])      # digested in the inter-diff
        old = os.environ.get("CRUCIBLE_CATALOG_DIGEST")
        os.environ["CRUCIBLE_CATALOG_DIGEST"] = "0"                             # raw diffs everywhere, as asked
        try:
            self.assertEqual(sorted(V.since_texts(files, [])), ["a.py", "de.po", "fr.po"])
        finally:
            if old is None:
                os.environ.pop("CRUCIBLE_CATALOG_DIGEST", None)
            else:
                os.environ["CRUCIBLE_CATALOG_DIGEST"] = old

    def test_full_review_prompt_has_no_since_block(self):
        ch = {"files": ["a.py"], "text": "diff"}
        args = ("o__r", "a" * 40, "b" * 40, ch, "rules", "mem", "facts", "log", ["a.py"])
        self.assertNotIn("RE-REVIEW", V.review_prompt(*args))
        self.assertIn("This pass covers: a.py\n\n        Diff for this pass:", V.review_prompt(*args))


class TestSymbolCollisions(unittest.TestCase):
    """BLAZE escape #1 (idea only): two changes each GREEN on their own redefined the same SQL function."""

    FN = "CREATE OR REPLACE FUNCTION public.add_user(n text) RETURNS void AS $$ select 1 $$ LANGUAGE sql;\n"

    def setUp(self):
        home = tempfile.mkdtemp()
        orig = (U.HOME, R.gh_json, R.upstream_slug)
        U.HOME, R.upstream_slug = home, (lambda repo: None)
        R.gh_json = lambda *a: self.fail(f"unexpected gh call {a}")
        self.addCleanup(lambda: (setattr(U, "HOME", orig[0]), setattr(R, "gh_json", orig[1]),
                                 setattr(R, "upstream_slug", orig[2])))

    @staticmethod
    def _files(repo, rng="main...HEAD"):
        return D.parse(sh(repo, "git", "diff", rng))

    def test_same_sql_function_on_the_tracking_ref_fails_and_names_the_commit(self):
        repo = make_repo({"db/migrations/001_init.sql": "select 1;\n"},
                         {"db/migrations/002_mine.sql": self.FN})
        base = sh(repo, "git", "rev-parse", "main")
        sh(repo, "git", "checkout", "-q", "main")
        open(os.path.join(repo, "db/migrations/002_theirs.sql"), "w").write(
            'create function "add_user"(n text) returns void as $$ select 2 $$ language sql;\n')
        sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", "theirs: add_user v2")
        sh(repo, "git", "checkout", "-q", "fix")
        files = self._files(repo, f"{base}..HEAD")
        self.assertEqual(R.symbol_collisions(repo, base, files, offline=True)["status"], "pass")
        r = R.symbol_collisions(repo, base, files, offline=True, base_ref="main")
        self.assertEqual(r["status"], "fail", r)
        self.assertIn("SQL function add_user", r["evidence"]); self.assertIn("theirs: add_user v2", r["evidence"])

    def test_other_open_pr_defining_the_same_symbol_warns_from_the_cache(self):
        repo = make_repo({"app/util.py": "x = 1\n"}, {"app/util.py": "x = 1\n\n\ndef load_config(path):\n    return path\n"})
        R.upstream_slug = lambda repo: "o/r"
        page = {"data": {"repository": {"pullRequests": {"totalCount": 2, "pageInfo": {"hasNextPage": False},
                "nodes": [{"number": n, "url": f"https://github.com/o/r/pull/{n}", "isDraft": False, "headRefOid": h,
                           "author": {"login": who, "__typename": "User"}, "files": {"nodes": [{"path": p}]}}
                          for n, h, who, p in ((41, "abc", "ann", "app/util.py"), (42, "def", "me", "app/util.py"))]}}}}
        R.gh_json = lambda *a: page if a[0] == "graphql" else self.fail(f"cache miss {a}")
        os.makedirs(os.path.dirname(R._defs_cache_path("o/r", 41)))
        U.write_json(R._defs_cache_path("o/r", 41), {"head": "abc", "at": time.time(), "got": {
            "defs": [["file", "app/util.py", "load_config", None]], "unread": [], "cut": False}})
        r = R.symbol_collisions(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo), me="me")
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("#41 by ann (https://github.com/o/r/pull/41): load_config in app/util.py", r["evidence"])
        self.assertNotIn("#42", r["evidence"])                                  # our own PR

    def test_other_pr_patch_is_read_and_cached(self):
        repo = make_repo({"q.sql": "select 1;\n"}, {"q.sql": "select 1;\n" + self.FN})
        R.upstream_slug = lambda repo: "o/r"
        page = {"data": {"repository": {"pullRequests": {"totalCount": 1, "pageInfo": {"hasNextPage": False},
                "nodes": [{"number": 7, "url": "u/7", "isDraft": False, "headRefOid": "h7",
                           "author": {"login": "bo", "__typename": "User"}, "files": {"nodes": [{"path": "other.sql"}]}}]}}}}
        R.gh_json = lambda *a: page if a[0] == "graphql" else [
            {"filename": "other.sql", "patch": "@@ -0,0 +1 @@\n+CREATE VIEW add_user AS select 1;\n"
                                               "+  CREATE   FUNCTION ADD_USER(t TEXT) returns int"}]
        r = R.symbol_collisions(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo), me="me")
        self.assertEqual(r["status"], "warn", r); self.assertIn("#7 by bo", r["evidence"])
        self.assertEqual(U.read_json(R._defs_cache_path("o/r", 7))["head"], "h7")

    def test_no_definitions_is_na(self):
        repo = make_repo({"README.md": "a\n"}, {"README.md": "a\nCREATE FUNCTION foo_bar() is how you do it\n",
                                                 "docs/x.md": "def load_config(): docs\n"})
        r = R.symbol_collisions(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo), offline=True)
        self.assertEqual(r["status"], "na", r)

    def test_falsifiers_call_sites_comments_and_noise_are_not_definitions(self):
        for path, line in (("a.sql", "-- CREATE OR REPLACE FUNCTION add_user()"),
                           ("a.sql", "/* CREATE FUNCTION add_user() */"),
                           ("a.sql", "select add_user('x');"),
                           ("a.py", "    def load_config(self):"),             # a method, not top level
                           ("a.py", "load_config(path)"),
                           ("a.py", "def __init__(self):"),
                           ("a.py", "def run():"),                             # under 4 characters
                           ("a.rb", "  def initialize(x)"),
                           ("a.rb", "  def perform"),                          # a method: its class isn't on the line
                           ("a.sql", "CREATE TRIGGER set_updated_at"),         # its table is on a later line
                           ("a.js", "  function inner() {}"),
                           ("a.js", "const helper = () => 1"),                 # not exported
                           ("a.txt", "def load_config():"),
                           ("notes.md", "CREATE OR REPLACE FUNCTION add_user()")):
            self.assertEqual(R._definitions(path, line), [], (path, line))
        for path, line, label in (("m/a.go", "func (s *Server) Handle(w int) {", "Server.Handle in package m"),
                                  ("a.ts", "export default async function loadConfig() {", "loadConfig in a.ts"),
                                  ("a.rb", "def self.load_config", "load_config in a.rb"),
                                  ("x.sql", "CREATE MATERIALIZED VIEW IF NOT EXISTS stats.daily AS", "SQL view stats.daily")):
            self.assertEqual([lb for _, lb in R._definitions(path, line)], [label], (path, line))

    def test_triggers_on_other_tables_and_overloads_are_different_symbols(self):
        # self-review CR-59ca34df: set_updated_at on every table, and add_user(text) vs add_user(int), are not collisions
        key = lambda line: R._definitions("m.sql", line)[0][0]
        self.assertFalse(R._collides(key("CREATE TRIGGER set_updated_at BEFORE UPDATE ON users"),
                                     key("CREATE TRIGGER set_updated_at BEFORE UPDATE ON orders")))
        self.assertTrue(R._collides(key("CREATE TRIGGER set_updated_at BEFORE UPDATE ON users"),
                                    key('create trigger "set_updated_at" before update on public.users')))
        self.assertFalse(R._collides(key("CREATE FUNCTION add_user(n text) RETURNS void"),
                                     key("CREATE FUNCTION add_user(n int) RETURNS void")))
        self.assertTrue(R._collides(key("CREATE FUNCTION add_user(n text, OUT id int) RETURNS"),
                                    key("CREATE OR REPLACE FUNCTION public.add_user(text) RETURNS")))
        self.assertTrue(R._collides(key("CREATE FUNCTION add_user("),                   # args on later lines: unknown
                                    key("CREATE FUNCTION add_user(n int) RETURNS void")))
        repo = make_repo({"db/migrations/001.sql": "select 1;\n"},
                         {"db/migrations/002_a.sql": "CREATE TRIGGER set_updated_at BEFORE UPDATE ON users\n"})
        base = sh(repo, "git", "rev-parse", "main")
        sh(repo, "git", "checkout", "-q", "main")
        open(os.path.join(repo, "db/migrations/002_b.sql"), "w").write(
            "CREATE TRIGGER set_updated_at BEFORE UPDATE ON orders\n")
        sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", "orders trigger")
        sh(repo, "git", "checkout", "-q", "fix")
        r = R.symbol_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "pass", r)
        # self-review CR-bc8a4140 / CR-d2db059f: a landed trigger on the same table names its commit, and an
        # upper-case extension on the tracking ref is still read
        sh(repo, "git", "checkout", "-q", "main")
        open(os.path.join(repo, "db/migrations/003_C.SQL"), "w").write(
            "create trigger SET_UPDATED_AT after insert on public.users\n")
        sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", "users trigger upstream")
        sh(repo, "git", "checkout", "-q", "fix")
        r = R.symbol_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "fail", r)
        self.assertIn("SQL trigger set_updated_at on users (in ", r["evidence"])
        self.assertIn("users trigger upstream", r["evidence"])

    def test_go_collides_per_package_not_across_packages(self):
        repo = make_repo({"svc/a.go": "package svc\n", "web/a.go": "package web\n"},
                         {"svc/b.go": "package svc\n\nfunc LoadConfig() {}\n"})
        base = sh(repo, "git", "rev-parse", "main")
        sh(repo, "git", "checkout", "-q", "main")
        open(os.path.join(repo, "web/c.go"), "w").write("package web\n\nfunc LoadConfig() {}\n")
        sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", "web config")
        files = self._files(repo, f"{base}..fix")
        self.assertEqual(R.symbol_collisions(repo, base, files, offline=True, base_ref="main")["status"], "pass")
        open(os.path.join(repo, "svc/c.go"), "w").write("package svc\n\nfunc LoadConfig() {}\n")
        sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", "svc config")
        r = R.symbol_collisions(repo, base, files, offline=True, base_ref="main")
        self.assertEqual(r["status"], "fail", r); self.assertIn("LoadConfig in package svc", r["evidence"])

    def _one_pr(self, files_payload, head="h9", path="other.sql"):
        R.upstream_slug = lambda repo: "o/r"
        page = {"data": {"repository": {"pullRequests": {"totalCount": 1, "pageInfo": {"hasNextPage": False},
                "nodes": [{"number": 9, "url": "u/9", "isDraft": False, "headRefOid": head,
                           "author": {"login": "cy", "__typename": "User"}, "files": {"nodes": [{"path": path}]}}]}}}}
        calls = []
        R.gh_json = lambda *a: page if a[0] == "graphql" else (calls.append(a) or files_payload)
        return calls

    def test_patchless_or_truncated_pr_warns_instead_of_passing(self):
        # self-review CR-281932b9: a file sent without a patch, or a PR past one page of files, isn't "no definitions"
        repo = make_repo({"q.sql": "select 1;\n"}, {"q.sql": "select 1;\n" + self.FN})
        base, files = sh(repo, "git", "rev-parse", "main"), self._files(repo)
        self._one_pr([{"filename": "other.sql", "changes": 9000}])
        r = R.symbol_collisions(repo, base, files, me="me")
        self.assertEqual(r["status"], "warn", r); self.assertIn("couldn't be read in full", r["evidence"])
        self._one_pr([{"filename": f"f{i}.txt", "patch": "@@ -1 +1 @@\n+x", "changes": 1} for i in range(100)],
                     head="h10")
        self.assertEqual(R.symbol_collisions(repo, base, files, me="me")["status"], "warn")
        self._one_pr([{"filename": "other.sql", "patch": "@@ -0,0 +1 @@\n+select 2;", "changes": 1}], head="h11")
        self.assertEqual(R.symbol_collisions(repo, base, files, me="me")["status"], "pass")

    def test_stale_or_corrupt_cache_is_refetched(self):
        repo = make_repo({"q.sql": "select 1;\n"}, {"q.sql": "select 1;\n" + self.FN})
        base, files = sh(repo, "git", "rev-parse", "main"), self._files(repo)
        path = R._defs_cache_path("o/r", 9)
        os.makedirs(os.path.dirname(path))
        hit = {"defs": [["sql", "function", "add_user", None]], "unread": [], "cut": False}
        for cached in ({"head": "old", "at": time.time(), "got": hit},                    # the PR moved
                       {"head": "h9", "at": time.time() - R.HUNK_CACHE_TTL - 1, "got": hit},
                       {"head": "h9", "at": time.time(), "got": {"defs": [["sql", "x"]], "unread": [], "cut": False}}):
            U.write_json(path, cached)
            calls = self._one_pr([{"filename": "other.sql", "patch": "@@ -0,0 +1 @@\n+select 2;", "changes": 1}])
            self.assertEqual(R.symbol_collisions(repo, base, files, me="me")["status"], "pass", cached)
            self.assertEqual(len(calls), 1, cached)

    def test_evaluate_wires_the_base_ref_and_offline(self):
        repo = make_repo({"db/migrations/001_init.sql": "select 1;\n"}, {"db/migrations/002_mine.sql": self.FN})
        base = sh(repo, "git", "rev-parse", "main")
        sh(repo, "git", "checkout", "-q", "main")
        open(os.path.join(repo, "db/migrations/002_theirs.sql"), "w").write(self.FN)
        sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", "theirs")
        sh(repo, "git", "checkout", "-q", "fix")
        item = lambda res: next(i for i in res["items"] if i["item"] == "no other change redefines the same symbols")
        files = self._files(repo, f"{base}..HEAD")
        res = R.evaluate(repo, "o__r", base, files, offline=True, base_ref="main")
        self.assertEqual(item(res)["status"], "fail"); self.assertFalse(res["ready"])
        self.assertIn("open PRs not checked (offline)", item(res)["evidence"])
        self.assertEqual(item(R.evaluate(repo, "o__r", base, files, offline=True))["status"], "pass")


class TestGeneratedOutputs(unittest.TestCase):
    """BLAZE escape #3 (idea only): a hand edit to a generated file passed review and was overwritten by the next
    codegen run; an input changed without its generated output."""

    GO_HDR = "// Code generated by protoc-gen-go. DO NOT EDIT.\n// source: api/user.proto\n\npackage api\n"

    @staticmethod
    def _files(repo, rng="main...HEAD"):
        return D.parse(sh(repo, "git", "diff", rng))

    def _run(self, repo):
        return R.generated_outputs(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo))

    def test_hand_edited_pb_go_without_its_proto_warns(self):
        repo = make_repo({"api/user.proto": "message User { string name = 1; }\n",
                          "api/user.pb.go": self.GO_HDR + "type User struct{ Name string }\n"},
                         {"api/user.pb.go": self.GO_HDR + "type User struct{ Name string; Age int }\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("api/user.pb.go", r["evidence"]); self.assertIn("api/user.proto", r["evidence"])
        self.assertIn("Move any hand edit into the input, then regenerate", r["evidence"])

    def test_proto_and_output_changed_together_pass(self):
        repo = make_repo({"api/user.proto": "message User { string name = 1; }\n",
                          "api/user.pb.go": self.GO_HDR + "type User struct{ Name string }\n"},
                         {"api/user.proto": "message User { string name = 1; int32 age = 2; }\n",
                          "api/user.pb.go": self.GO_HDR + "type User struct{ Name string; Age int32 }\n"})
        self.assertEqual(self._run(repo)["status"], "pass")

    def test_proto_changed_without_its_output_warns_and_names_the_generate_command(self):
        repo = make_repo({"api/user.proto": "message User { string name = 1; }\n",
                          "api/user.pb.go": self.GO_HDR + "type User struct{ Name string }\n",
                          "Makefile": "generate:\n\tprotoc --go_out=. api/*.proto\n"},
                         {"api/user.proto": "message User { string name = 1; int32 age = 2; }\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("api/user.proto changed but api/user.pb.go did not", r["evidence"])
        self.assertIn("`make generate`", r["evidence"])

    def test_sqlc_source_header_maps_output_to_its_query_file(self):
        hdr = "// Code generated by sqlc. DO NOT EDIT.\n// source: queries.sql\n\npackage db\n"
        repo = make_repo({"db/queries.sql": "-- name: GetUser :one\nselect 1;\n", "db/queries.sql.go": hdr + "x\n"},
                         {"db/queries.sql.go": hdr + "y\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "warn", r); self.assertIn("db/queries.sql", r["evidence"])

    def test_linguist_generated_attribute_and_npm_script(self):
        repo = make_repo({".gitattributes": "src/schema.ts linguist-generated=true\n", "schema.graphql": "type Q { a: Int }\n",
                          "src/schema.ts": "export type Q = { a: number }\n",
                          "package.json": '{"scripts": {"test": "jest", "codegen": "graphql-codegen"}}'},
                         {"src/schema.ts": "export type Q = { a: number; b: string }\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("linguist-generated", r["evidence"]); self.assertIn("`npm run codegen`", r["evidence"])

    def test_openapi_client_edited_without_the_spec_warns(self):
        hdr = "/* Generated by OpenAPI Generator. Do not edit the class manually. */\n"
        repo = make_repo({"openapi.yaml": "openapi: 3.0.0\n", "src/client/api.ts": hdr + "export const a = 1\n"},
                         {"src/client/api.ts": hdr + "export const a = 2\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "warn", r); self.assertIn("openapi.yaml", r["evidence"])

    def test_two_ci_jobs_writing_the_same_generated_file_warn(self):
        wf = ("on: push\njobs:\n  gen:\n    runs-on: x\n    steps:\n      - run: tool > src/types.gen.ts\n"
              "  docs:\n    runs-on: x\n    steps:\n      - run: other --output src/types.gen.ts\n")
        repo = make_repo({".github/workflows/ci.yml": wf, "src/types.gen.ts": "a\n"}, {"src/types.gen.ts": "b\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("ci.yml:gen", r["evidence"]); self.assertIn("ci.yml:docs", r["evidence"])
        self.assertIn("Keep one job writing it", r["evidence"]); self.assertNotIn("regenerate", r["evidence"])

    def test_artifact_upload_and_download_are_not_competing_writers(self):
        wf = ("on: push\njobs:\n  build:\n    steps:\n      - uses: actions/upload-artifact@v4\n        with:\n"
              "          path: src/types.gen.ts\n  test:\n    steps:\n      - uses: actions/download-artifact@v4\n"
              "        with:\n          path: src/types.gen.ts\n")
        repo = make_repo({".github/workflows/ci.yml": wf, "src/types.gen.ts": "a\n"}, {"src/types.gen.ts": "b\n"})
        self.assertEqual(self._run(repo)["status"], "pass")

    def test_regenerated_after_an_imported_proto_changed_is_not_a_hand_edit(self):
        repo = make_repo({"api/common.proto": "message Id { string v = 1; }\n", "api/user.proto": "import \"common.proto\";\n",
                          "api/user.pb.go": self.GO_HDR + "type User struct{ Id string }\n"},
                         {"api/common.proto": "message Id { int64 v = 1; }\n",
                          "api/user.pb.go": self.GO_HDR + "type User struct{ Id int64 }\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "pass", r); self.assertIn("api/common.proto changed, which may be why", r["evidence"])

    def test_a_package_json_bump_or_a_far_away_sql_file_does_not_excuse_a_hand_edit(self):
        for extra in ({"package.json": '{"version": "2"}\n'}, {"db/migrations/0002_x.sql": "select 2;\n"},
                      {"Makefile": "all:\n\ttrue\n"}, {"package.json": '{"description": "a protocol handler"}\n'},
                      {"go.mod": "module x\nrequire golang.org/x/net v0.30.0\nrequire google.golang.org/grpc v1.70.0\n"}):
            repo = make_repo({"api/user.proto": "message User {}\n", "api/user.pb.go": self.GO_HDR + "a\n",
                              "package.json": '{"version": "1"}\n', "Makefile": "x:\n\ttrue\n"},
                             {"api/user.pb.go": self.GO_HDR + "b\n", **extra})
            r = self._run(repo)
            self.assertEqual(r["status"], "warn", (extra, r))

    def test_sqlc_output_regenerated_after_its_sibling_schema_changed_passes(self):
        hdr = "// Code generated by sqlc. DO NOT EDIT.\n// source: query.sql\n\npackage db\n"
        repo = make_repo({"db/query/query.sql": "select 1;\n", "db/schema/schema.sql": "create table u(a int);\n",
                          "db/query/query.sql.go": hdr + "a\n"},
                         {"db/schema/schema.sql": "create table u(a bigint);\n", "db/query/query.sql.go": hdr + "b\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "pass", r); self.assertIn("db/schema/schema.sql changed, which may be why", r["evidence"])

    def test_root_migration_excuses_a_regenerated_sqlc_output_but_not_a_protobuf_one(self):
        hdr = "// Code generated by sqlc. DO NOT EDIT.\n// source: queries.sql\n\npackage db\n"
        repo = make_repo({"migrations/0001_init.sql": "create table u(a int);\n", "internal/db/queries.sql": "select 1;\n",
                          "internal/db/queries.sql.go": hdr + "a\n"},
                         {"migrations/0002_b.sql": "alter table u add b int;\n", "internal/db/queries.sql.go": hdr + "b\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "pass", r); self.assertIn("migrations/0002_b.sql changed, which may be why", r["evidence"])

    def test_a_generator_version_bump_excuses_regenerated_output(self):
        repo = make_repo({"api/user.proto": "message User {}\n", "api/user.pb.go": self.GO_HDR + "a\n",
                          "go.mod": "module x\nrequire google.golang.org/protobuf v1.30.0\n"},
                         {"api/user.pb.go": self.GO_HDR + "b\n", "go.mod": "module x\nrequire google.golang.org/protobuf v1.34.0\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "pass", r); self.assertIn("go.mod changed, which may be why", r["evidence"])

    def test_grpcio_tools_bump_excuses_a_regenerated_pb2(self):
        repo = make_repo({"proto/user.proto": "message User {}\n", "proto/user_pb2.py": "# @generated\na = 1\n",
                          "requirements.txt": "grpcio-tools==1.60.0\n"},
                         {"proto/user_pb2.py": "# @generated\na = 2\n", "requirements.txt": "grpcio-tools==1.66.0\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "pass", r); self.assertIn("requirements.txt changed, which may be why", r["evidence"])

    def test_hand_edit_and_stale_output_together_give_one_fix(self):
        repo = make_repo({"api/user.proto": "message User {}\n", "api/user.pb.go": self.GO_HDR + "a\n",
                          "web/ui.proto": "message Ui {}\n",
                          "web/ui.pb.go": "// Code generated by protoc-gen-go. DO NOT EDIT.\n// source: web/ui.proto\n"},
                         {"api/user.pb.go": self.GO_HDR + "b\n", "web/ui.proto": "message Ui { int32 a = 1; }\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("api/user.pb.go", r["evidence"]); self.assertIn("web/ui.proto changed but web/ui.pb.go", r["evidence"])
        self.assertEqual(r["evidence"].count("regenerate with"), 1, r["evidence"])

    def test_a_long_single_line_file_is_read_only_up_to_the_byte_budget(self):
        heads = {}
        repo = make_repo({"big.min.js": "x" * 200000})
        self.assertEqual(len(R._head(repo, "big.min.js", heads)), R.GEN_HEAD_BYTES)

    def test_sqlc_query_changed_without_its_go_output_warns(self):
        hdr = "// Code generated by sqlc. DO NOT EDIT.\n// source: queries.sql\n\npackage db\n"
        repo = make_repo({"db/queries.sql": "-- name: GetUser :one\nselect 1;\n", "db/queries.sql.go": hdr + "x\n"},
                         {"db/queries.sql": "-- name: GetUser :one\nselect 2;\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("db/queries.sql changed but db/queries.sql.go did not", r["evidence"])

    def test_output_with_another_stem_found_through_its_source_header(self):
        hdr = "// Code generated by protoc-gen-go-grpc. DO NOT EDIT.\n// source: api/user.proto\n\npackage api\n"
        repo = make_repo({"api/user.proto": "service U {}\n", "api/user_service.pb.go": hdr + "x\n"},
                         {"api/user.proto": "service U { rpc Get(A) returns (B); }\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "warn", r); self.assertIn("api/user_service.pb.go did not", r["evidence"])

    def test_openapi_spec_changed_without_its_client_warns(self):
        hdr = "/* Generated by OpenAPI Generator. Do not edit the class manually. */\n"
        repo = make_repo({"openapi.yaml": "openapi: 3.0.0\n", "src/client/api.ts": hdr + "export const a = 1\n"},
                         {"openapi.yaml": "openapi: 3.0.0\npaths: {}\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("openapi.yaml changed but src/client/api.ts did not", r["evidence"])

    def test_plain_config_yaml_next_to_a_generated_file_is_not_an_input(self):
        repo = make_repo({"conf/app.yaml": "a: 1\n", "conf/app.pb.go": self.GO_HDR + "x\n"}, {"conf/app.yaml": "a: 2\n"})
        self.assertEqual(self._run(repo)["status"], "na")

    def test_new_generated_file_with_no_identified_input_passes(self):
        repo = make_repo({"a.py": "x = 1\n"}, {"gen/out.generated.ts": "// @generated\nexport {}\n"})
        self.assertEqual(self._run(repo)["status"], "pass")

    def test_prose_lockfiles_vendor_and_plain_config_are_na(self):
        repo = make_repo({"README.md": "x\n", "package-lock.json": "{}\n", "vendor/lib/x.pb.go": "a\n",
                          "config.yaml": "a: 1\n", "src/app.py": "x = 1\n"},
                         {"README.md": "The docs are generated from the code; do not edit them by hand.\n",
                          "package-lock.json": '{"a": 1}\n', "vendor/lib/x.pb.go": "b\n", "config.yaml": "a: 2\n",
                          "src/app.py": "# this value is generated at runtime\nx = 2\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "na", r)

    def test_a_json_file_with_the_same_stem_elsewhere_is_not_an_input(self):
        repo = make_repo({"conf/settings.json": "{}\n", "web/settings.generated.ts": "export {}\n"},
                         {"web/settings.generated.ts": "export const a = 1\n"})
        r = self._run(repo)
        self.assertEqual(r["status"], "pass", r); self.assertIn("input not identified", r["evidence"])

    def test_evaluate_includes_the_item(self):
        repo = make_repo({"a.js": "1\n"}, {"a.js": "2\n"})
        base = sh(repo, "git", "rev-parse", "main")
        items = R.evaluate(repo, "t__gen", base, self._files(repo), offline=True)["items"]
        self.assertIn({"item": "generated files regenerated with their inputs", "status": "na",
                       "evidence": "no generated file or generator input in the change"}, items)


class TestCountCollisions(unittest.TestCase):
    """A test asserts a bare count(*) of a shared table; another change adds rows to that table in its own migration.
    Each is green alone; together the number is off. Fixtures written from scratch."""

    SEED = "CREATE TABLE app.kinds (id int, kind text);\nINSERT INTO app.kinds VALUES (1, 'a'), (2, 'b');\n"
    GATE = ('#!/bin/sh\nset -e\nn=$(psql -tAc "select count(*) from app.kinds")\n'
            '[ "$n" -eq 2 ] || { echo "expected 2 kinds, got $n"; exit 1; }\n')

    def setUp(self):
        home = tempfile.mkdtemp()
        orig = (U.HOME, R.gh_json, R.upstream_slug)
        U.HOME, R.upstream_slug = home, (lambda repo: None)
        R.gh_json = lambda *a: self.fail(f"unexpected gh call {a}")
        self.addCleanup(lambda: (setattr(U, "HOME", orig[0]), setattr(R, "gh_json", orig[1]),
                                 setattr(R, "upstream_slug", orig[2])))

    @staticmethod
    def _files(repo, rng="main...HEAD"):
        return D.parse(sh(repo, "git", "diff", rng))

    def _landed(self, mine, theirs_path, theirs_text):
        repo = make_repo({"db/migrations/001_seed.sql": self.SEED}, mine)
        base = sh(repo, "git", "rev-parse", "main")
        sh(repo, "git", "checkout", "-q", "main")
        os.makedirs(os.path.join(repo, os.path.dirname(theirs_path)), exist_ok=True)
        open(os.path.join(repo, theirs_path), "w").write(theirs_text)
        sh(repo, "git", "add", "-A"); sh(repo, "git", "commit", "-qm", "theirs: more kinds")
        sh(repo, "git", "checkout", "-q", "fix")
        return repo, base

    def test_gate_script_count_vs_rows_landed_on_the_tracking_ref_fails(self):
        repo, base = self._landed({"ci/gate_kinds.sh": self.GATE}, "db/migrations/002_more.sql",
                                  "insert into kinds (id, kind) values (3, 'c'), (4, 'd');\n")
        r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "fail", r)
        self.assertIn("app.kinds gets rows from db/migrations/002_more.sql", r["evidence"])
        self.assertIn("theirs: more kinds", r["evidence"]); self.assertIn("measure the count", r["evidence"])

    def test_combined_string_literal_in_a_python_test_counts(self):
        test = ('def test_counts(db):\n    got = db.one("select count(*) from app.kinds")\n'
                '    assert f"0/0/{got}" == "0/0/2"\n')
        repo, base = self._landed({"tests/test_kinds.py": test}, "db/seeds/kinds.sql",
                                  "DELETE FROM app.kinds WHERE id = 2;\n")
        r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "fail", r)

    def test_open_pr_writing_the_table_warns_and_is_cached(self):
        repo = make_repo({"db/migrations/001_seed.sql": self.SEED}, {"ci/gate_kinds.sh": self.GATE})
        R.upstream_slug = lambda repo: "o/r"
        page = {"data": {"repository": {"pullRequests": {"totalCount": 2, "pageInfo": {"hasNextPage": False},
                "nodes": [{"number": n, "url": f"https://github.com/o/r/pull/{n}", "isDraft": False, "headRefOid": h,
                           "author": {"login": who, "__typename": "User"}, "files": {"nodes": [{"path": p}]}}
                          for n, h, who, p in ((51, "h51", "ann", "db/migrations/003_x.sql"),
                                               (52, "h52", "bo", "src/app.py"))]}}}}
        R.gh_json = lambda *a: page if a[0] == "graphql" else (
            [{"filename": "db/migrations/003_x.sql", "patch": "@@ -0,0 +1 @@\n+INSERT INTO \"app\".\"kinds\" VALUES (9, 'z');"}]
            if "/51/" in a[0] else self.fail(f"unexpected fetch {a}"))
        r = R.count_collisions(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo), me="me")
        self.assertEqual(r["status"], "warn", r)
        self.assertIn("#51 by ann (https://github.com/o/r/pull/51) writes rows to app.kinds", r["evidence"])
        self.assertNotIn("#52", r["evidence"])                            # touched no SQL: never fetched
        self.assertEqual(U.read_json(os.path.join(U.HOME, "cache", "pr-writes", "o__r", "51.json"))["head"], "h51")

    def test_falsifiers(self):
        cases = {
            "filtered to own keys": "n=$(psql -tAc \"select count(*) from app.kinds where kind = 'mine'\")\n[ \"$n\" -eq 1 ] || exit 1\n",
            "filtered on the next line": "n=$(psql -tAc \"select count(*) from app.kinds\n where id in (1, 2)\")\n[ \"$n\" -eq 2 ] || exit 1\n",
            "other table": "n=$(psql -tAc \"select count(*) from app.colors\")\n[ \"$n\" -eq 2 ] || exit 1\n",
            "local temp table": "psql -c \"create temp table kinds (id int)\"\nn=$(psql -tAc \"select count(*) from kinds\")\n[ \"$n\" -eq 0 ] || exit 1\n",
            "no asserted number": "psql -tAc \"select count(*) from app.kinds\" > counts.txt\n",
            "lower bound": "n=$(psql -tAc \"select count(*) from app.kinds\")\n[ \"$n\" -gt 0 ] || exit 1\n",
            "non-empty check": "n=$(psql -tAc \"select count(*) from app.kinds\")\n[ \"$n\" -ne 0 ] || exit 1\n",
            "empty check": "n=$(psql -tAc \"select count(*) from app.kinds\")\n[ -z \"$n\" ] && exit 1\n",
        }
        files = {label: ("ci/gate_kinds.sh", g) for label, g in cases.items()}
        files["python != 0"] = ("tests/test_kinds.py", 'def test_k(db):\n    got = db.one("select count(*) from app.kinds")\n'
                                '    if got != 0:\n        return\n    raise AssertionError("empty")\n')
        files["shell != \"0\""] = ("ci/gate_kinds.sh", 'n=$(psql -tAc "select count(*) from app.kinds")\n[ "$n" != "0" ] || exit 1\n')
        files["python != 0.0"] = ("tests/test_kinds.py", 'def test_k(db):\n    got = db.one("select count(*) from app.kinds")\n'
                                  '    if got != 0.0:\n        return\n    raise AssertionError("empty")\n')
        files["js !== 0"] = ("tests/kinds.test.js", 'test("k", async () => {\n  const got = await one("select count(*) from app.kinds");\n'
                             '  expect(got !== 0).toBe(true);\n});\n')
        for label, (path, gate) in files.items():
            with self.subTest(label):
                repo, base = self._landed({path: gate}, "db/migrations/002_more.sql",
                                          "insert into app.kinds values (3, 'c');\n")
                r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
                self.assertIn(r["status"], ("na", "pass"), r)

    def test_table_the_test_file_creates_outside_the_diff_is_local(self):
        gate = "psql -c \"create temp table kinds (id int)\"\n"
        repo = make_repo({"db/migrations/001_seed.sql": self.SEED, "ci/gate_kinds.sh": gate},
                         {"ci/gate_kinds.sh": gate + "n=$(psql -tAc \"select count(*) from kinds\")\n[ \"$n\" -eq 0 ] || exit 1\n"})
        r = R.count_collisions(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo), offline=True)
        self.assertEqual(r["status"], "na", r)

    def test_system_catalog_counts_are_ignored(self):
        repo = make_repo({"a.py": "x = 1\n"}, {"tests/test_conn.py":
                         'def test_conns(db):\n    assert db.one("select count(*) from pg_stat_activity") == 1\n'})
        r = R.count_collisions(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo), offline=True)
        self.assertEqual(r["status"], "na", r)

    def test_fail_unless_exactly_n_counts(self):
        cases = (("-ne 2", "ci/gate_kinds.sh", 'n=$(psql -tAc "select count(*) from app.kinds")\n[ "$n" -ne 2 ] && exit 1\n'),
                 ("python != 2", "tests/test_kinds.py", 'def test_k(db):\n    got = db.one("select count(*) from app.kinds")\n'
                  '    if got != 2:\n        raise AssertionError(got)\n'),
                 ("combined 0/0/$n", "ci/gate_kinds.sh",
                  'n=$(psql -tAc "select count(*) from app.kinds")\n[ "0/0/$n" != "0/0/2" ] && exit 1\n'))
        for label, path, gate in cases:
            with self.subTest(label):
                repo, base = self._landed({path: gate}, "db/migrations/002_more.sql", "insert into app.kinds values (3, 'c');\n")
                r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
                self.assertEqual(r["status"], "fail", r)

    def test_sql_named_with_a_gate_word_outside_gate_dirs_is_a_writer(self):
        # deliberate (see _sql_writer_file): db/check_kinds.sql inserting rows counts as a writer
        repo, base = self._landed({"ci/gate_kinds.sh": self.GATE}, "db/check_kinds.sql",
                                  "insert into app.kinds values (3, 'c');\n")
        r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "fail", r)

    def test_rspec_eq_without_parentheses_counts(self):
        spec = 'it "seeds" do\n  n = conn.select_value("select count(*) from app.kinds")\n  expect(n).to eq 2\nend\n'
        repo, base = self._landed({"spec/kinds_spec.rb": spec}, "db/migrations/002_more.sql",
                                  "insert into app.kinds values (3, 'c');\n")
        r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "fail", r)

    def test_gate_sql_seeding_its_own_rows_is_not_a_writer(self):
        repo, base = self._landed({"ci/gate_kinds.sh": self.GATE}, "ci/check_kinds.sql",
                                  "insert into app.kinds values (3, 'c');\n")
        r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "pass", r)

    def test_writer_named_like_a_test_word_still_counts(self):
        repo, base = self._landed({"ci/gate_kinds.sh": self.GATE}, "db/migrations/002_latest_kinds.sql",
                                  "insert into app.kinds values (3, 'c');\n")
        r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "fail", r)

    def test_same_named_temp_table_does_not_hide_a_qualified_count(self):
        gate = "psql -c \"create temp table kinds (id int)\"\n" + self.GATE
        repo, base = self._landed({"ci/gate_kinds.sh": gate}, "db/migrations/002_more.sql",
                                  "insert into app.kinds values (3, 'c');\n")
        r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "fail", r)

    def _pr_page(self, n=61, head="h61", path="db/migrations/004_y.sql"):
        return {"data": {"repository": {"pullRequests": {"totalCount": 1, "pageInfo": {"hasNextPage": False},
                "nodes": [{"number": n, "url": f"u/{n}", "isDraft": False, "headRefOid": head,
                           "author": {"login": "cy", "__typename": "User"}, "files": {"nodes": [{"path": path}]}}]}}}}

    def test_open_pr_paths_cache_hit_fetch_failure_and_patchless(self):
        repo = make_repo({"db/migrations/001_seed.sql": self.SEED}, {"ci/gate_kinds.sh": self.GATE})
        base = sh(repo, "git", "rev-parse", "main")
        R.upstream_slug = lambda repo: "o/r"
        page = self._pr_page()
        os.makedirs(os.path.join(U.HOME, "cache", "pr-writes", "o__r"))
        U.write_json(os.path.join(U.HOME, "cache", "pr-writes", "o__r", "61.json"),
                     {"head": "h61", "at": time.time(), "got": {"tables": ["app.kinds"], "unread": [], "cut": False}})
        R.gh_json = lambda *a: page if a[0] == "graphql" else self.fail(f"cache miss {a}")
        r = R.count_collisions(repo, base, self._files(repo), me="me")
        self.assertEqual(r["status"], "warn", r); self.assertIn("#61 by cy", r["evidence"])
        page = self._pr_page(head="h62")                                          # new head: re-fetch, which fails
        R.gh_json = lambda *a: page if a[0] == "graphql" else None
        r = R.count_collisions(repo, base, self._files(repo), me="me")
        self.assertEqual(r["status"], "warn", r); self.assertIn("1 couldn't be fetched", r["evidence"])
        page = self._pr_page(head="h63")                                          # a SQL file sent without a patch
        R.gh_json = lambda *a: page if a[0] == "graphql" else [{"filename": "db/migrations/004_y.sql", "changes": 900}]
        r = R.count_collisions(repo, base, self._files(repo), me="me")
        self.assertEqual(r["status"], "warn", r); self.assertIn("couldn't be read in full (#61)", r["evidence"])

    def test_same_name_in_another_schema_does_not_count(self):
        repo, base = self._landed({"ci/gate_kinds.sh": self.GATE}, "db/migrations/002_more.sql",
                                  "insert into audit.kinds values (3, 'c');\n")
        r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "pass", r)

    def test_rows_written_by_a_test_fixture_do_not_count(self):
        repo, base = self._landed({"ci/gate_kinds.sh": self.GATE}, "tests/fixtures/kinds.sql",
                                  "insert into app.kinds values (3, 'c');\n")
        r = R.count_collisions(repo, base, self._files(repo, f"{base}..HEAD"), offline=True, base_ref="main")
        self.assertEqual(r["status"], "pass", r)

    def test_count_in_non_test_code_is_na(self):
        repo = make_repo({"a.py": "x = 1\n"}, {"src/report.py": 'q = "select count(*) from app.kinds"\nassert q\nLIMIT = 2\n'})
        r = R.count_collisions(repo, sh(repo, "git", "rev-parse", "main"), self._files(repo), offline=True)
        self.assertEqual(r["status"], "na", r)

    def test_wired_into_evaluate(self):
        repo = make_repo({"a.py": "x = 1\n"}, {"a.py": "x = 2\n"})
        names = [i["item"] for i in R.evaluate(repo, "p", sh(repo, "git", "rev-parse", "main"),
                                                 self._files(repo), offline=True)["items"]]
        self.assertIn("no other change moves a table a test counts", names)




class TestNitTier(unittest.TestCase):
    """--nits: a verified non-blocking tier kept apart from the findings (ReviewBench 2026-11-11, low recall 27%)."""

    @staticmethod
    def _f(title, line, severity="low", file="a.py"):
        return {"severity": severity, "file": file, "line": line, "title": title, "problem": "p",
                "caused_by_this_change": True, "reachable_in_real_use": True, "wrong_if": "w", "fix": "x"}

    def _run(self, nits_out, verdicts=None, nits=True, env=None, fail_batch=False):
        """-> (review.json, calls). The fake reviewer returns one important finding and `nits_out` as nits; the nit
        verifier answers `verdicts` (index -> (keep, confidence)), default keep/high for every nit."""
        from unittest import mock
        repo = make_repo({"a.py": "x = 1\n"}, {"a.py": "x = 2\n" + "".join(f"y{i} = {i}\n" for i in range(30))})
        calls = []

        def fake(prompt, model, schema, cwd, budget=None, *a, **kw):
            calls.append({"kind": kw.get("kind"), "model": model, "schema": schema, "prompt": prompt})
            if "findings" in schema["properties"]:
                out = {"summary": "s", "findings": [self._f("division by zero in f", 1, "important")]}
                if "nits" in schema["properties"]:
                    out["nits"] = nits_out
                return out, 0.1
            if "verdicts" in schema["properties"]:
                if fail_batch:
                    raise U.Failed("usage limit")
                budget.add(0.05)                                 # what the real claude() does with the CLI's cost
                n = prompt.count("Falsification test:")
                vs = verdicts or {}
                return {"verdicts": [{"index": i, "keep": vs.get(i, (True, "high"))[0], "severity": "low",
                                      "confidence": vs.get(i, (True, "high"))[1], "evidence": f"e{i}"}
                                     for i in range(n) if vs.get(i, (True, "high")) is not None]}, 0.05
            return {"keep": True, "severity": "important", "method": "read", "actions": "", "evidence": "e",
                    "confidence": "high"}, 0.02
        home = tempfile.mkdtemp(prefix="crucible-home-")
        with mock.patch.object(V, "HOME", home), mock.patch.object(U, "HOME", home), mock.patch.object(V, "claude", fake), \
                mock.patch.dict(os.environ, dict({"CRUCIBLE_CACHE": os.path.join(home, "c")}, **(env or {}))):
            d = V.run_review(repo, "main", offline=True, skip_checks=True, log=lambda *_: None, nits=nits)
            return U.read_json(os.path.join(d, "review.json")), calls

    def test_off_by_default_prompt_schema_and_record_unchanged(self):
        r, calls = self._run([self._f("a nit", 2)], nits=None)
        review = [c for c in calls if c["kind"] == "review"]
        self.assertIs(review[0]["schema"], V.FINDINGS_SCHEMA)
        self.assertNotIn("Second tier", review[0]["prompt"])
        self.assertNotIn("verify_nits", [c["kind"] for c in calls])
        self.assertNotIn("nits", r); self.assertNotIn("nits", r["inputs"])
        self.assertNotIn("## Nits", V.report(r, {}))

    def test_env_turns_it_on(self):
        r, _ = self._run([self._f("a nit", 2)], nits=None, env={"CRUCIBLE_NITS": "1"})
        self.assertEqual([f["title"] for f in r["nits"]], ["a nit"])

    def test_verified_nits_kept_apart_and_never_in_the_verdict(self):
        nits = [self._f("missing docstring on new public f", 2), self._f("magic number 30", 5, "medium"),
                self._f("comment contradicts loop bound", 8), self._f("speculative concern", 11)]
        r, calls = self._run(nits, verdicts={2: (True, "low"), 3: (False, "high")})
        self.assertEqual(sorted(f["title"] for f in r["nits"]), ["magic number 30", "missing docstring on new public f"])
        self.assertEqual({f["verification"]["status"] for f in r["nits"]}, {"verified"})
        self.assertEqual(len(r["nits_dropped"]), 2)              # a low-confidence keep is not a keep
        self.assertTrue(all(f["id"].startswith("NIT-") for f in r["nits"]))
        self.assertEqual([f["title"] for f in r["findings"]], ["division by zero in f"])
        _, blocking, unanswered = V.verdict(r, {})
        self.assertEqual([f["title"] for f in unanswered], ["division by zero in f"])   # nits are never "unanswered"
        self.assertEqual(V.verdict(r, {r["findings"][0]["id"]: {"disposition": "fixed", "note": "n"}})[0], "GREEN")
        nit_calls = [c for c in calls if c["kind"] == "verify_nits"]
        self.assertEqual(len(nit_calls), 1)                      # one batch, on the mid model
        self.assertEqual(nit_calls[0]["model"], U.MODELS["sonnet"])
        self.assertIn("## Nits (non-blocking", V.report(r, {}))
        self.assertGreater(r["cost_nits_usd"], 0)

    def test_nit_repeating_a_finding_or_another_nit_is_left_out(self):
        r, calls = self._run([self._f("division by zero in f", 1), self._f("magic number 30", 5),
                              self._f("magic number 30", 5)])
        self.assertEqual([f["title"] for f in r["nits"]], ["magic number 30"])
        self.assertEqual(calls[-1]["prompt"].count("Falsification test:"), 1)

    TEN = ["unclosed file handle", "docstring says seconds", "README flag renamed", "retry loop never sleeps",
           "empty list crashes max", "error swallowed silently", "timeout default changed", "unused import added",
           "lock held across await", "log leaks token"]

    def test_nits_are_batched(self):
        r, calls = self._run([self._f(w, i + 2) for i, w in enumerate(self.TEN)])
        self.assertEqual(len(r["nits"]), 10)
        self.assertEqual(sum(c["kind"] == "verify_nits" for c in calls), 1)
        with unittest.mock.patch.object(V, "NIT_BATCH", 4):
            r, calls = self._run([self._f(w, i + 2) for i, w in enumerate(self.TEN[:9])])
        self.assertEqual(sum(c["kind"] == "verify_nits" for c in calls), 3)
        self.assertEqual([c["prompt"].count("Falsification test:") for c in calls if c["kind"] == "verify_nits"], [4, 4, 1])
        self.assertEqual(len(r["nits"]), 9)

    def test_failed_or_missing_verdict_drops_the_nit(self):
        r, _ = self._run([self._f("a nit", 2), self._f("another unrelated thing", 9)], fail_batch=True)
        self.assertEqual(r["nits"], [])
        self.assertEqual({f["verification"]["status"] for f in r["nits_dropped"]}, {"unverified"})
        self.assertEqual(len(r["findings"]), 1)                  # the findings don't depend on the nit tier
        r, _ = self._run([self._f("a nit", 2), self._f("another unrelated thing", 9)], verdicts={1: None})
        self.assertEqual([f["title"] for f in r["nits"]], ["a nit"])

    def test_nit_cap_stops_spending(self):
        r, calls = self._run([self._f("a nit", 2)], env={"CRUCIBLE_NITS_MAX_USD": "0"})
        self.assertNotIn("verify_nits", [c["kind"] for c in calls])
        self.assertEqual(r["nits"], []); self.assertEqual(r["cost_nits_usd"], 0)

    def test_sub_budget(self):
        parent = U.Budget(1.0)
        sub = V.SubBudget(parent, 0.3)
        self.assertAlmostEqual(sub.remaining(), 0.3)
        sub.add(0.2)
        self.assertAlmostEqual(parent.spent, 0.2); self.assertAlmostEqual(sub.remaining(), 0.1)
        parent.add(0.75)
        self.assertAlmostEqual(sub.remaining(), 0.05)            # whichever runs out first
        sub.add(0.1)
        self.assertTrue(sub.exhausted())
        self.assertAlmostEqual(V.SubBudget(U.Budget(None), 0.5).remaining(), 0.5)

    def test_a_review_without_nits_is_redone_for_nits_not_the_reverse(self):
        prev = {"status": "done", "inputs": {"base": "b", "draft": None, "draft_sha": None}, "findings": []}
        self.assertIn("--nits", V.stale_inputs(prev, V.review_inputs(".", "b", nits=True) | {"draft": None, "draft_sha": None}))
        prev["inputs"]["nits"] = True
        self.assertIsNone(V.stale_inputs(prev, {"base": "b", "draft": None, "draft_sha": None}))

    def test_eval_scores_nits_separately(self):
        from crucible import evalrun as E
        rev = {"status": "done", "findings": [], "dropped": [], "cost_usd": 1,
               "nits": [{"severity": "low", "file": "a.py", "line": 3, "title": "off by one", "problem": ""}],
               "nits_dropped": [{}], "cost_nits_usd": 0.2}
        s = E.score_case(rev, {"kind": "bug", "file": "a.py", "lines": [3], "keywords": []})
        self.assertEqual((s["nits"], s["nits_dropped"], s["nit_hits"], s["caught"]), (1, 1, 1, False))
        self.assertEqual(s["nit_list"], [{"severity": "low", "file": "a.py", "line": 3, "title": "off by one",
                                          "confidence": None}])
        self.assertNotIn("nits", E.score_case({k: v for k, v in rev.items() if k != "nits"},
                                              {"kind": "clean"}))


class TestReviewBenchAdapter(unittest.TestCase):
    def _mod(self, env=None):
        import importlib.util
        from unittest import mock
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bench", "reviewbench", "to_findings.py")
        with mock.patch.dict(os.environ, env or {}):
            spec = importlib.util.spec_from_file_location("rb_to_findings", p)
            m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
        return m

    @staticmethod
    def _f(sev, line, title="t"):
        return {"severity": sev, "file": "./src/a.py", "line": line, "title": title, "problem": "p"}

    def test_no_cap_by_default_and_most_severe_first(self):
        m = self._mod()
        rev = {"findings": [self._f("low", i + 1) for i in range(100)] + [self._f("critical", 500)]}
        out = m.to_findings(rev)
        self.assertEqual(len(out), 101)                          # the first run capped at 60
        self.assertEqual(out[0]["start_line"], 500); self.assertTrue(out[0]["message"].startswith("[critical]"))
        self.assertEqual(out[1]["file"], "src/a.py")

    def test_nits_follow_findings_of_the_same_severity_and_a_cap_drops_them_first(self):
        m = self._mod()
        rev = {"findings": [self._f("low", 1, "finding"), self._f("important", 2, "finding")],
               "nits": [self._f("medium", 3, "nit"), self._f("low", 4, "nit")]}
        self.assertEqual([o["start_line"] for o in m.to_findings(rev)], [2, 3, 1, 4])
        self.assertEqual([o["start_line"] for o in m.to_findings(rev, cap=3)], [2, 3, 1])
        self.assertEqual(len(self._mod({"RB_CONFIG_MAX_FINDINGS": "2"}).to_findings(rev)), 2)

    def test_pr_text_and_lineless_findings_left_out(self):
        m = self._mod()
        rev = {"findings": [dict(self._f("low", 1), file="PR_DRAFT.md"), dict(self._f("low", 1), line=None)],
               "nits": [dict(self._f("low", 0))]}
        self.assertEqual(m.to_findings(rev), [])


if __name__ == "__main__":
    unittest.main()
