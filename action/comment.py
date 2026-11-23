#!/usr/bin/env python3
"""The action's last step: turn crucible's report into a PR comment, and post it or update the earlier one.

  comment.py build REPORT BODY     report -> comment body (marker, header, secrets scrubbed, cut to GitHub's limit)
  comment.py post BODY             create or update the comment on $PR in $GITHUB_REPOSITORY (needs gh + GH_TOKEN)

The crucible CLI never posts. This script is the only part that does, and only in a workflow someone added to
their own repository."""
import json, os, subprocess, sys

MARKER = "<!-- crucible-report -->"
LIMIT = 65000                        # GitHub refuses comment bodies over 65,536 characters


def build(report, sha, dry_run=False, secrets=(), verdict=""):
    lines = [ln for ln in report.splitlines() if not ln.startswith("(report: ")]
    text = "\n".join(lines).strip()
    for s in secrets:                # a finding that quotes the key (e.g. a prompt-injected diff) must not publish it
        if s and len(s) >= 8:
            text = text.replace(s, "***")
    head = f"{MARKER}\n**crucible** on `{sha[:10]}`" + (f": **{verdict}**" if verdict else "")
    if dry_run:
        head += " (dry run: no model was called, the finding below is a placeholder)"
    body = f"{head}\n\n<details><summary>Report</summary>\n\n{text}\n\n</details>\n"
    if len(body) > LIMIT:
        cut = "\n\n[cut: the report is longer than a GitHub comment allows; the full report is in the job log]\n"
        keep = LIMIT - len(head) - len(cut) - 60
        body = f"{head}\n\n<details><summary>Report</summary>\n\n{text[:keep]}{cut}\n</details>\n"
    return body


def gh(*args, data=None):
    r = subprocess.run(["gh", "api", *args] + (["--input", "-"] if data is not None else []),
                       input=json.dumps(data) if data is not None else None, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"gh api {args[0]}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout or "null")


def post(body, repo, pr):
    """Update this action's earlier comment on the PR (a bot comment carrying MARKER), or create one. -> its URL."""
    mine = None
    for page in gh(f"repos/{repo}/issues/{pr}/comments?per_page=100", "--paginate", "--slurp"):
        for c in page:
            if MARKER in (c.get("body") or "") and (c.get("user") or {}).get("type") == "Bot":
                mine = c
    if mine:
        return gh(f"repos/{repo}/issues/comments/{mine['id']}", "-X", "PATCH", data={"body": body})["html_url"]
    return gh(f"repos/{repo}/issues/{pr}/comments", "-X", "POST", data={"body": body})["html_url"]


def main(argv):
    if argv[:1] == ["build"] and len(argv) == 3:
        report = open(argv[1], encoding="utf-8", errors="replace").read()
        secrets = [os.environ.get(k, "") for k in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")]
        body = build(report, os.environ.get("SHA", ""), os.environ.get("DRY_RUN") == "true", secrets,
                     os.environ.get("VERDICT", ""))
        open(argv[2], "w", encoding="utf-8").write(body)
    elif argv[:1] == ["post"] and len(argv) == 2:
        print(post(open(argv[1], encoding="utf-8").read(), os.environ["GITHUB_REPOSITORY"], os.environ["PR"]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
