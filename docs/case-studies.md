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

## three-mesh-bvh #959: a miss, and the check it produced

[gkjohnson/three-mesh-bvh#959](https://github.com/gkjohnson/three-mesh-bvh/pull/959) was GREEN locally and then failed CI. The project's workflow tests three.js 0.159.0, 0.168.0 and latest; the local run only had 0.185.0 installed, and the new test called `getComponent`, which 0.159's `InterleavedBufferAttribute` doesn't have (36 failing cases).

crucible didn't flag it: nothing told it which versions CI runs. The fix, pushed to the PR, was a small test change (+6/−3): compare with `getX/getY/getZ`, which 0.159 also has. crucible gained a readiness item, "CI dependency matrix tried locally": it reads `strategy.matrix` axes from the workflows, matches them to declared dependencies and names the versions you haven't tried, with the install command for the oldest. Across 29 real clones, only the three-mesh-bvh ones warn.

## How these were picked

Since 2026-11-04, crucible has reviewed changes to 11 upstream projects before submission. These are cases where the public PR shows the result. Most kept findings are low (wording, tests, descriptions); `crucible stats` gives the current fixed, deferred and refuted counts for your own reviews.
