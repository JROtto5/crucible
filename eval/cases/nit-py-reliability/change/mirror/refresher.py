import logging
import os
import threading
import time

from mirror.fetch import fetch

log = logging.getLogger(__name__)


class Refresher:
    """Re-downloads the mirrored index every `interval` seconds in the background."""

    def __init__(self, url, cache_dir, interval=300):
        self.url = url
        self.cache_dir = cache_dir
        self.interval = interval

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()
        return t

    def _run(self):
        while True:
            try:
                data = fetch(self.url)
            except OSError as exc:
                log.warning("index refresh failed, keeping the old copy: %s", exc)
            else:
                tmp = os.path.join(self.cache_dir, "index.json.tmp")
                with open(tmp, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, os.path.join(self.cache_dir, "index.json"))
            time.sleep(self.interval)
