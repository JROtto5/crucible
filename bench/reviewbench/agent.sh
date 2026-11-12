#!/usr/bin/env bash
# ReviewBench adapter: one PR in, one findings file out. crucible runs in its normal review configuration
# (Opus review, tiered verification), with two benchmark-forced changes: --offline (no GitHub API exists here)
# and --skip-checks (the project's dependencies are not installed, so its lint/test commands cannot run). --nits adds the
# verified non-blocking tier: the golden set is 52% low severity, which the blocking-oriented findings mostly skip.
set -uo pipefail
export HOME=/tmp/home CRUCIBLE_HOME=/tmp/crucible CLAUDE_CONFIG_DIR=/tmp/claude-config PYTHONDONTWRITEBYTECODE=1
mkdir -p "$HOME" "$CRUCIBLE_HOME" "$CLAUDE_CONFIG_DIR"
repo=${RB_REPO:-/work/repo}
budget=${RB_CONFIG_BUDGET:-5}
echo "crucible $(python -c 'import crucible;print(crucible.__version__)') budget=$budget mode=offline,skip-checks,nits"
git config --global --add safe.directory '*'
git config --global user.email bench@example.invalid; git config --global user.name bench
# name the project the way crucible expects (no network: the remote is never fetched)
git -C "$repo" remote get-url origin >/dev/null 2>&1 || git -C "$repo" remote add origin "https://github.com/${RB_NWO}.git"
# the PR description is part of what crucible reads; keep it out of the commit (crucible excludes it itself)
jq -r '"# " + (.title // "") + "\n\n" + (.body // "")' "$RB_PR_JSON" > "$repo/PR_DRAFT.md"
grep -qx 'PR_DRAFT.md' "$repo/.git/info/exclude" 2>/dev/null || echo PR_DRAFT.md >> "$repo/.git/info/exclude"
timeout ${RB_CONFIG_TIMEOUT:-3300} crucible review "$repo" --base "$RB_BASE" --offline --skip-checks --full --nits --budget "$budget" > /tmp/review.log 2>&1
rc=$?
tail -n 5 /tmp/review.log
echo "crucible exit $rc"
python /agent/to_findings.py "$CRUCIBLE_HOME" > "$RB_OUT"
out_rc=$?
# RB_CONFIG_KEEP_REVIEW=1: leave crucible's review.json beside the findings (for private scoring of the nit tier;
# the judge reads only findings.json)
if [ "${RB_CONFIG_KEEP_REVIEW:-0}" = 1 ]; then
  find "$CRUCIBLE_HOME/reviews" -name review.json -path "*/$RB_HEAD/*" -exec cp {} "$(dirname "$RB_OUT")/review.json" \; 2>/dev/null
fi
exit $out_rc
