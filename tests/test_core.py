import json, os, re, subprocess, sys, tempfile, unittest

_TMP_HOME = tempfile.mkdtemp(prefix="crucible-test-home-")
os.environ["CRUCIBLE_HOME"] = _TMP_HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crucible import diff as D, readiness as R, review as V, routing as RT, style as S, util as U  # noqa: E402

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



class TestLearnedDataVersion(unittest.TestCase):
    """umu's style.json kept a Dependabot-polluted 879-word median after bug j was fixed, because nothing re-ran
    `learn`. Learned files are stamped with the `learn` version, and readiness says what an older file misses."""
    def write(self, project, fname, data):
        with open(os.path.join(U.project_dir(project), fname), "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))

    def test_not_learned(self):
        self.assertEqual(R.learned_data("lv__none")["status"], "na")

    def test_unstamped_files_warn_with_everything_they_miss(self):
        self.write("lv__old", "meta.json", {"learned": "2026-11-04", "median_merged_pr_lines": 40})
        self.write("lv__old", "style.json", {"body": {"median_words": 879}})
        it = R.learned_data("lv__old")
        self.assertEqual(it["status"], "warn")
        self.assertIn("meta.json (unstamped, learned 2026-11-04), style.json (unstamped)", it["evidence"])
        for v in range(2, U.LEARN_VERSION + 1):
            self.assertIn(U.LEARN_CHANGES[v], it["evidence"])
        self.assertIn("Re-run `crucible learn`", it["evidence"])

    def test_names_only_the_changes_since_the_stamp(self):
        self.write("lv__v2", "style.json", {"learn_version": 2})
        self.write("lv__v2", "meta.json", {"learn_version": U.LEARN_VERSION})
        it = R.learned_data("lv__v2")
        self.assertEqual(it["status"], "warn")
        self.assertNotIn("meta.json", it["evidence"])
        self.assertNotIn(U.LEARN_CHANGES[2], it["evidence"])
        self.assertIn("style.json (v2); `crucible learn` is now v3, and since v3: " + U.LEARN_CHANGES[3], it["evidence"])

    def test_current_stamp_passes_and_a_bump_makes_it_stale(self):
        self.write("lv__cur", "style.json", {"learn_version": U.LEARN_VERSION})
        self.assertEqual(R.learned_data("lv__cur")["status"], "pass")
        orig = (U.LEARN_VERSION, U.LEARN_CHANGES)
        try:  # falsifier: the same file is stale once a later `learn` fix bumps the version
            U.LEARN_VERSION, U.LEARN_CHANGES = orig[0] + 1, {**orig[1], orig[0] + 1: "a later fix"}
            it = R.learned_data("lv__cur")
            self.assertEqual(it["status"], "warn")
            self.assertIn("a later fix", it["evidence"])
        finally:
            U.LEARN_VERSION, U.LEARN_CHANGES = orig

    def test_unreadable_or_odd_stamps_count_as_v1(self):
        self.write("lv__bad", "style.json", "{not json")
        self.write("lv__bad", "meta.json", {"learn_version": True})
        it = R.learned_data("lv__bad")
        self.assertEqual(it["status"], "warn")
        self.assertIn("meta.json (unstamped), style.json (unstamped)", it["evidence"])

    def test_every_version_says_what_changed(self):
        self.assertEqual(sorted(U.LEARN_CHANGES), list(range(2, U.LEARN_VERSION + 1)))

    def test_run_learn_stamps_meta(self):
        from crucible import learn as L
        repo = make_repo({"a.py": "x = 1\n"})
        sh(repo, "git", "remote", "add", "origin", "https://github.com/o/lv.git")
        orig = (L.collect, L.docs_text)
        L.collect, L.docs_text = (lambda slug, n, log: ([], [], [10, 20])), (lambda slug: "")
        try:
            meta = L.run_learn(repo, style=False, log=lambda *_: None)
        finally:
            L.collect, L.docs_text = orig
        self.assertEqual(meta["learn_version"], U.LEARN_VERSION)
        self.assertEqual(R.learned_data(U.project_key(repo))["status"], "pass")


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
        self.assertEqual(sizes, [2, 2])

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
            if exp["kind"] == "bug":
                self.assertTrue(exp["file"] and exp["lines"] and exp["keywords"], name)
                self.assertTrue(os.path.exists(os.path.join(d, "change", exp["file"])), name)


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

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500):
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

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500):
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

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500):
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

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500):
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

        def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500):
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

                def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500):
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

            def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500):
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

        def fake(prompt, model, schema, cwd, budget=None, tools=None, effort="high", timeout=1500):
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
        finally:
            V.HOME, U.HOME, V.claude = olds[0], olds[1], olds[2]
            if olds[3] is None:
                os.environ.pop("CRUCIBLE_CACHE", None)
            else:
                os.environ["CRUCIBLE_CACHE"] = olds[3]


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


if __name__ == "__main__":
    unittest.main()
