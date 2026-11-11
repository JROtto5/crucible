# Quickstart

A real run on a public repo, timed. Measured 2026-11-11 with crucible from `main` (57f110f). Your times and costs will differ with the size of the change.

You need Python 3.10+, git, `gh` (logged in) and the [Claude Code](https://claude.com/claude-code) CLI.

## 1. Install

```sh
pipx install git+https://github.com/JROtto5/crucible@57f110f   # the build these numbers come from
```

## 2. Make a change to review

The example replays a real bug from [pyinfra-dev/pyinfra](https://github.com/pyinfra-dev/pyinfra), a project whose [AI policy](https://github.com/pyinfra-dev/pyinfra/blob/HEAD/AI_POLICY.md) allows AI-assisted work. Merged PR [#1587](https://github.com/pyinfra-dev/pyinfra/pull/1587) added `requires_command` to the four iptables facts. Its tests didn't exercise the broken path, and it shipped a crash that [#1730](https://github.com/pyinfra-dev/pyinfra/pull/1730) fixed later. Here the PR is re-applied on its own base, as if you were about to submit it:

```sh
git clone https://github.com/pyinfra-dev/pyinfra && cd pyinfra
uv sync && . .venv/bin/activate              # the project's own dev environment
git switch -c iptables-requires 09116428^
git cherry-pick 09116428                      # the change from #1587
gh pr view 1587 --json body --jq .body > PR_DRAFT.md
```

`PR_DRAFT.md` is the PR description you plan to submit. crucible reviews it too.

## 3. Learn the project (126 s, $0.10, once per project)

```sh
crucible learn .
```

Reads the project's merged PRs and maintainer comments and writes its house style and rules (20 rules and a PR-body style from 20 PRs here). It also finds the checks to run: `ruff check .` and `python3 -m pytest -q -x` for this repo.

## 4. Review (139 s, $0.54)

```sh
crucible review .
```

The project's checks run first: ruff passed. pytest failed, but on `test_apt_packages_update_cached`, an apt cache test that depends on today's date, not on this change. A failing check keeps the verdict NOT_GREEN unless it fails on the base too: `crucible review . --base-checks` re-runs failing checks on the base to show that. Then a model different from the one that wrote the change reviewed it, and a verification pass tried to disprove each finding. All three survived:

- **critical**, `facts/iptables.py:95`: *requires_command() takes no args, so every iptables operation crashes with TypeError*. `get_fact` passes the fact's arguments (`table=...`) to `requires_command` too, and `iptables.rule` and `iptables.chain` always pass `table`. This is the bug #1730 fixed.
- **important**: the test fixtures never pass `table`, so the crash path is untested. That's why the project's own tests passed.
- **low**: the PR description ticks "Tests pass" but lists no commands and no linked issue.

Every finding says what would prove it wrong, and the report is pinned to the commit you reviewed. crucible refuses to review uncommitted changes, so the verdict always matches `HEAD`.

## 5. Fix, re-review, answer

Apply the fix #1730 used, `def requires_command(self, *args, **kwargs)` in the four facts, commit (`git commit -a --amend` works), and run `crucible review .` again (155 s, $0.32 here). Later rounds only re-review what changed. The critical finding is gone, and the missing-fixture finding stays open until a fixture passes `table` (for example `"arg": {"table": "nat"}` in a new `tests/facts/iptables.*` fixture). This run stopped there, so the steps below are not timed.

Answer each remaining finding:

```sh
crucible answer CR-xxxxxxxx fixed|refuted|deferred "why"
```

A refuted or deferred answer needs a reason, and it's shown in the report. Once nothing blocking is open and everything is answered, the verdict is **GREEN**. `crucible status` shows the verdict and the readiness checklist at any time. crucible never posts anything: you submit the PR yourself.

## The run in numbers

| step | wall time | cost |
|---|---|---|
| learn | 126 s | $0.10 |
| review, round 1 (the crash found) | 139 s | $0.54 |
| review, round 2 (after the fix) | 155 s | $0.32 |

The real bug was found about four and a half minutes after starting, for $0.64.

The same day, another real pyinfra change ([#2030](https://github.com/pyinfra-dev/pyinfra/pull/2030), sed escaping in `crontab`) was a miss: the reviewer raised the over-escaping of `^` and `$` that [#2040](https://github.com/pyinfra-dev/pyinfra/pull/2040) later fixed, and verification dropped it as harmless. [docs/case-studies.md](case-studies.md) has more catches and misses on upstream PRs.
