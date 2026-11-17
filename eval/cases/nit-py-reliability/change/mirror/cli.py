import argparse
import sys

import pathlib

from mirror.fetch import fetch, head
from mirror.prune import prune


def main(argv=None):
    p = argparse.ArgumentParser(prog="mirror")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("size")
    s.add_argument("url")
    g = sub.add_parser("pull")
    g.add_argument("url")
    g.add_argument("dest")
    r = sub.add_parser("prune")
    r.add_argument("cache_dir")
    r.add_argument("--max-age-days", type=float, default=7)
    args = p.parse_args(argv)
    if args.cmd == "size":
        print(head(args.url))
    elif args.cmd == "pull":
        pathlib.Path(args.dest).write_bytes(fetch(args.url))
        print(args.dest)
    elif args.cmd == "prune":
        n = prune(args.cache_dir, args.max_age_days * 86400)
        print(f"removed {n} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
