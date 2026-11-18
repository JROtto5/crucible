"""python -m bench.logins: time 8k logins and logouts."""
import time

from sessions.registry import Registry

if __name__ == "__main__":
    r = Registry()
    t = time.perf_counter()
    for i in range(8000):
        r.login(i)
    for i in range(8000):
        r.logout(i)
    print(f"{(time.perf_counter() - t) * 1000:.1f} ms")
