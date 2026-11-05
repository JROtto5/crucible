import os, re, subprocess, sys, tempfile, unittest

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
    """Regression tests for bugs found while reviewing real upstream PRs (BOARD a–e)."""

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

    def test_previous_review_requires_ancestor_same_base_and_complete(self):
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
        calls = self.stub({None: self.page([(7003, "b", "User", ["src/Library.tsx"])], 1)}, {})  # patch unreadable
        it = R.overlapping_prs(".", self.OURS, "me")
        self.assertEqual(it["status"], "warn")
        self.assertIn("1 couldn't be compared, no readable patch (#7003)", it["evidence"])

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
                        found.append({"severity": "medium", "file": "src/b.js", "line": 2, "title": "g has no test",
                                      "problem": "untested", "caused_by_this_change": True, "reachable_in_real_use": True,
                                      "wrong_if": "a test covers g", "fix": "add a test"})
                    return {"summary": "s", "findings": found}, 0.01
                if "changed since then" in prompt:      # the re-check of the carried b.js finding: a test was added
                    return {"keep": False, "severity": "medium", "method": "read", "actions": "read test",
                            "evidence": "test/g.test.js covers g", "confidence": "high"}, 0.001
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
                self.assertEqual(r2["incremental"]["carried"], 1)            # g has no test (b.js untouched)
                self.assertEqual(r2["incremental"]["reverified"], 1)         # f reads past the end (a.js touched)
                self.assertTrue(any(c[2] for c in calls))                    # the re-check saw the later changes
                kept_titles = {f["title"] for f in r2["findings"]}
                self.assertNotIn("g has no test", kept_titles)               # dropped by the re-check
                self.assertIn("g has no test", {f["title"] for f in r2["dropped"]})
                self.assertTrue(r2["coverage"]["complete"])
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
                            (("src/a.js", "f reads past the end"), ("src/b.js", "g has no test")) if p in prompt]}, 0
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
                self.assertEqual(by["g has no test"]["status"], "unverified")
                self.assertIn("prose says falsified", by["g has no test"]["reason"])
                # round 2 touches only a.js: the b.js finding is carried and re-checked, and that re-check is transcribed
                w("src/a.js", "export const a = 1;\nexport function f(xs) { return xs[xs.length - 1]; }\n")
                g("commit", "-qam", "fix f")
                transcribed.clear()
                r2 = U.read_json(os.path.join(V.run_review(repo, "main", offline=True, skip_checks=True,
                                                           log=lambda *_: None), "review.json"))
                self.assertEqual(r2["status"], "done", r2.get("reason"))
                carried = [f for f in r2["findings"] if f["title"] == "g has no test"]
                self.assertEqual(len(carried), 1)
                self.assertIn("g has no test", transcribed)           # the re-check ran and was transcribed
                self.assertNotIn("rechecked", carried[0])
                self.assertEqual(carried[0]["verification"]["status"], "unverified")
                self.assertEqual(r2["dropped"], [])


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


if __name__ == "__main__":
    unittest.main()
