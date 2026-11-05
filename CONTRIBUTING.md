# Contributing to crucible

Thanks for helping. crucible is small, standard-library only, and judged by one thing: whether its findings hold up on real pull requests. These notes keep it that way.

## Reporting a wrong or missed finding

The most useful reports are real ones:

- **False positive:** a finding that was wrong. Open a "Wrong finding" issue with the finding block from `report.md` (title, file:line, verification evidence) and why it is wrong: the line that disproves it, or a command and its output.
- **Missed issue:** something a maintainer or CI caught that crucible didn't. Open a "Missed issue" issue with a link to the upstream review comment or failing run, if it's public.
- **Crash or wrong behaviour of a command:** open a "Bug" issue with the command, `crucible --version`, and the end of the output.

Don't paste private code or tokens. A short synthetic repro is fine, and a public PR link is better.

## Development setup

```bash
git clone https://github.com/JROtto5/crucible && cd crucible
pipx install --editable .          # or: python3 -m pip install --user --editable .
python3 -m unittest discover -s tests
python3 -m pip install ruff && ruff check .
```

The unit tests need only git and Python 3.10+. They stub every model call, cost nothing and run in about a second.

## What a change needs

1. **A test that fails without the change.** For a bug, reproduce it first. For a false-positive fix, add the real input that was misjudged as a regression case.
2. **Falsifiers for any new gate or heuristic.** List the inputs it must still flag and the inputs it must still let through, next to the code. Before you rely on it, check the first few real inputs it would reject by hand.
3. **`crucible eval` when prompts, verification or tiering change.** It runs the full review on 16 labelled fixture changes and calls the model (about $2–4 for all cases; `--cases NAME…` runs a few). Recall and false-blocking numbers must not get worse. Everything else is covered by the unit tests.
4. **One line in `CHANGELOG.md`**, dated, saying what changed for a user and why.
5. **A self-review.** Run `crucible review . --base <the commit before yours>` and answer every finding (`crucible answer CR-… fixed|refuted|deferred "…"`) until it is GREEN.

Keep the safe defaults: crucible never posts comments, never pushes, never approves, and never loads a checked-out project's `.claude/` settings. A change that weakens any of these won't be merged.

## Style

Standard library only. Comments explain the non-obvious *why*, the way the surrounding code does. Keep functions small enough to test with a stubbed model.
