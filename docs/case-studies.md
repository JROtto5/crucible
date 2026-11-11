# Case studies

Real catches, and one real miss, from crucible's reviews of upstream pull requests before they were submitted. Each case links the public PR, so you can check what shipped. Severities are crucible's own, after verification.

## supavisor #1273: the exception the PR didn't mention

[supabase/supavisor#1273](https://github.com/supabase/supavisor/pull/1273) makes Supavisor send a NOTICE when it drops a client's startup options (`PGOPTIONS='-c default_transaction_read_only=on'` used to be ignored without a word).

crucible (low, verified by reading the code): `jit` is in the list of options Supavisor treats as its own, because it is also Supavisor's JIT-auth flag. So a client's `-c jit=off`, a common PostgreSQL setting, was still dropped silently: the very behaviour the PR fixes, and the description didn't name it as an exception. The verifier traced it to `db_handler.ex`, which only forwards `jit` when proxying.

Outcome: a notice for `jit` would have fired for every normal client (`jit=false` is the default auth path), so the code stayed as it was. The PR description now says that a client's `-c jit=off` doesn't reach PostgreSQL, and the code comment says why. The reviewer reads that trade-off up front instead of finding it later.

## umu-launcher #740: documentation that would have applied the wrong game's fixes

[Open-Wine-Components/umu-launcher#740](https://github.com/Open-Wine-Components/umu-launcher/pull/740) documents how `GAMEID` sets the Steam app ID and window class. The first draft's workaround told users to give each app its own made-up `umu-<id>`.

crucible (low, verified by reading the code): `GAMEID` is also the key that protonfixes and the umu-database use. An invented id that matches a real entry (the same man page uses `umu-genshin` as an example a few lines up) silently applies that game's fixes to an unrelated app, and the section already said `umu-default` applies no fixes, so readers would assume invented ids are inert.

Outcome: the shipped text says to pick an id that is ideally not in the umu-database, "since the id also selects protonfixes".

## Lutris #7004: a fix that broke the case the previous round had covered

[lutris/lutris#7004](https://github.com/lutris/lutris/pull/7004) stops Lutris from quietly moving a plain Wine prefix to GE-Proton when the game's Wine version is missing; it now refuses to launch and says which version is gone.

crucible (medium, verified by running it): a rework between rounds dropped the case where the game itself is set to GE-Proton (Latest). `read_version_from_config()` treats that game-level choice as unset and falls through to the runner-wide version. When that build had been removed, the new guard told the user to "choose another Wine version for this game", a version they had already chosen. The verifier reproduced it: with the game on GE-Proton (Latest) and a plain prefix, `get_executable()` raised instead of returning the umu path. No test had the game set to GE-Proton.

Outcome: the merged guard skips games set to `GE_PROTON_LATEST`, and `test_game_set_to_ge_proton_falls_back` is in `tests/_test_wine.py`.

## Lutris #7006: a markup test that deleted the markup it was testing

[lutris/lutris#7006](https://github.com/lutris/lutris/pull/7006) repairs broken Pango markup in five translations, which GTK shows as an empty label, and adds a test that every translated string parses.

crucible (important, verified by running it): the first test removed every `<a ...>` tag with `</?a\b[^>]*>` before parsing, so a broken link could never fail. Four French strings still had broken links: `GitHub<a>` closing a link with an opening tag, and `href="…'` with mismatched quotes. The verifier set one of them on a real `Gtk.Label`: GTK logged a markup error and the label stayed empty. That is the bug the PR fixes, in strings the new test passed.

Outcome: the merged fr.po closes those links with `</a>`, and the test strips only well-formed links (one quote style, a closing `</a>`), so a broken one fails. The same round also flagged the msgmerge refresh bundled with the fix (medium). That was refuted, because the refresh was what the maintainer asked for. That round cost $19.45 for a 17k-line diff, which is why crucible now reads big catalog changes as an entry digest.

## three-mesh-bvh #959: a miss, and the check it produced

[gkjohnson/three-mesh-bvh#959](https://github.com/gkjohnson/three-mesh-bvh/pull/959) was GREEN locally and then failed CI. The project's workflow tests three.js 0.159.0, 0.168.0 and latest; the local run only had 0.185.0 installed, and the new test called `getComponent`, which 0.159's `InterleavedBufferAttribute` doesn't have (36 failing cases).

crucible didn't flag it: nothing told it which versions CI runs. The fix, pushed to the PR, was a small test change (+6/−3): compare with `getX/getY/getZ`, which 0.159 also has. crucible gained a readiness item, "CI dependency matrix tried locally": it reads `strategy.matrix` axes from the workflows, matches them to declared dependencies and names the versions you haven't tried, with the install command for the oldest. Across 29 real clones, only the three-mesh-bvh ones warn.

## Replays of merged PRs (pyinfra, 2026-11-11)

These are not our PRs. Each one re-applies a merged pyinfra PR on its own base and reviews it as if it were about to be submitted, so the later fix shows what was really wrong.

**Catch: [pyinfra-dev/pyinfra#1587](https://github.com/pyinfra-dev/pyinfra/pull/1587).** It added `requires_command` to the four iptables facts with no parameters. crucible (critical, verified by reading the code): `get_fact` passes the fact's arguments to `requires_command` too, and `iptables.rule` and `iptables.chain` always pass `table=`, so every iptables operation raises `TypeError`. It also flagged that no fixture passes `table`, which is why the project's tests passed. [#1730](https://github.com/pyinfra-dev/pyinfra/pull/1730) later fixed it with `requires_command(self, *args, **kwargs)`. This run is the [quickstart](quickstart.md).

**Miss: [pyinfra-dev/pyinfra#2030](https://github.com/pyinfra-dev/pyinfra/pull/2030).** It escaped sed special characters in `crontab`'s match pattern. The reviewer raised the escaping of `^` and `$`, and verification dropped it: `\^` and `\$` match literally in GNU sed, so it judged the extra escaping harmless. [#2040](https://github.com/pyinfra-dev/pyinfra/pull/2040) removed those two escapes three days later and changed the expected `interpolate_variables` commands. The kept findings were about the PR description and comments.

## How these were picked

Since 2026-11-04, crucible has reviewed changes to 11 upstream projects before submission. These are cases where the public PR shows the result. Most kept findings are low (wording, tests, descriptions); `crucible stats` gives the current fixed, deferred and refuted counts for your own reviews.
