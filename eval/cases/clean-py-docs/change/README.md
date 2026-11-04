# backoff

Exponential backoff helper.

`delay(attempt)` returns `min(cap, base * 2**attempt)` seconds, so with the
defaults the waits are 0.1, 0.2, 0.4 ... capped at 5 s.
