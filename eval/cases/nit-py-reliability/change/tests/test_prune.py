import os
import time

from mirror.prune import prune


def test_prune_removes_only_old_files(tmp_path):
    old = tmp_path / "old.bin"
    new = tmp_path / "new.bin"
    old.write_bytes(b"x")
    new.write_bytes(b"y")
    past = time.time() - 10 * 86400
    os.utime(old, (past, past))
    assert prune(str(tmp_path), 7 * 86400) == 1
    assert not old.exists() and new.exists()
