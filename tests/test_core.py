import os, subprocess, sys, tempfile, unittest

_TMP_HOME = tempfile.mkdtemp(prefix="crucible-test-home-")
os.environ["CRUCIBLE_HOME"] = _TMP_HOME
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crucible import diff as D, readiness as R, review as V, style as S, util as U  # noqa: E402


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
        self.assertTrue(d["notes"].startswith("## Explain it to me (Q&A prep)"))
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
        pre = "# Draft\n\n## Notes for me\nfile the issue first\n\n## Body\nFixes #5.\n\n## Explain it to me\nx\n"
        d = R.split_draft(pre)
        self.assertEqual(d["body"], "Fixes #5.")
        self.assertEqual(d["notes"], "## Explain it to me\nx")

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

    def test_evaluate_reads_only_the_submitted_part(self):
        d = make_repo({"a.js": "1\n"}, {"a.js": "2\n"})
        open(os.path.join(d, "PR_DRAFT.md"), "w").write(
            "# Fix a\n\nShort body, tested with npm test.\n\n## Explain it to me\nsee #77 for history\n")
        base = U.git(d, "merge-base", "main", "HEAD")
        files = D.parse(U.git(d, "diff", f"{base}..HEAD"))
        out = R.evaluate(d, "t__evaluate", base, files, offline=True)
        self.assertIsNone(out["issue"])  # #77 is in the author's notes, not the PR
        with open(os.path.join(d, "PR_DRAFT.md"), "w") as fh:
            fh.write("# Fix a\n\nFixes #12.\n\n## Explain it to me\nsee #77\n")
        self.assertEqual(R.evaluate(d, "t__evaluate", base, files, offline=True)["issue"], 12)

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
            for _ in range(3):  # later runs read PR_DRAFT.polished.md
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

if __name__ == "__main__":
    unittest.main()
