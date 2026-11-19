# jot

A day planner that keeps one note per date in `~/.jot.json`.

    jot add 2026-11-20 "dentist at 9"
    jot show 2026-11-20
    jot delete 2026-11-20

`jot delete DATE` removes the note for that date, so `jot show DATE` reports "No note" afterwards.

Run the tests with `python -m pytest`.
