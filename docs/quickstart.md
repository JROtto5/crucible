# Quickstart

A real run on a public repo, timed. Measured 2026-11-06 on a fresh install (crucible 0.3.0; 0.4.0 adds only this guide and the version bump); your times and costs will differ with the size of the change.

You need Python 3.10+, git, `gh` (logged in) and the [Claude Code](https://claude.com/claude-code) CLI.

## 1. Install (4 s)

```sh
pipx install git+https://github.com/JROtto5/crucible@v0.4.0
```

## 2. Make a change to review

The example uses [pallets/itsdangerous](https://github.com/pallets/itsdangerous) and a small "refactor" with a planted bug. It moves the signature age calculation into a helper and flips its sign by mistake:

```sh
git clone https://github.com/pallets/itsdangerous && cd itsdangerous
pip install -e . pytest freezegun          # the project's own test deps
git switch -c simplify-age
# edit src/itsdangerous/timed.py: age = self._age(ts_int), with
#     def _age(self, ts_int): return ts_int - self.get_timestamp()   # wrong order
git commit -am "Move the signature age calculation into a helper"
echo 'Move the signature age calculation in TimestampSigner.unsign into a helper, _age(), so it can be reused.' > PR_DRAFT.md
```

`PR_DRAFT.md` is the PR description you plan to submit. crucible reviews it too.

## 3. Learn the project (47 s, once per project)

```sh
crucible learn .
```

Reads the project's merged PRs and maintainer comments and writes its house style and rules (8 rules and a PR-body style from 18 PRs here). It also finds the checks to run: `ruff check .` and `python3 -m pytest -q -x` for this repo.

## 4. Review (66 s, $0.42)

```sh
crucible review .
```

The project's checks run first: pytest **failed**. Then a model different from the one that wrote the change reviewed it, and a verification pass tried to disprove each finding. What survived:

- **critical**, `timed.py`: *_age() subtracts in the wrong order: every past signature fails max_age, future ones pass*
- medium and low: the PR description has no testing evidence and no stated reason.

Every finding says what would prove it wrong, and the report is pinned to the commit you reviewed. crucible refuses to review uncommitted changes, so the verdict always matches `HEAD`.

## 5. Fix, re-review, answer (≈ 5 min over three rounds, $0.73)

Fix the bug, commit (`git commit -a --amend` works), and run `crucible review .` again. Later rounds only re-review what changed. Here they found two more real things:

- the new docstring, *"Seconds between ts_int and now"*, reads like a magnitude, which invites the same sign bug again;
- the reworded docstring broke the project's 88-column lint limit.

Answer each remaining finding:

```sh
crucible answer CR-xxxxxxxx fixed|refuted|deferred "why"
```

A refuted or deferred answer needs a reason, and it's shown in the report. Once nothing blocking is open and everything is answered, the verdict is **GREEN**. `crucible status` shows the verdict and the readiness checklist at any time. crucible never posts anything: you submit the PR yourself.

## The run in numbers

| step | wall time | cost |
|---|---|---|
| install | 4 s | – |
| learn | 47 s | – |
| review, round 1 (bug found) | 66 s | $0.42 |
| rounds 2–4 | 99 + 104 + 86 s | $0.73 |
| answers | < 1 s | – |

The first useful result came about two minutes after install. Reaching GREEN took about seven minutes of machine time and $1.15 in total.
