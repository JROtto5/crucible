import argparse
import sys

from mirror.fetch import head


def main(argv=None):
    p = argparse.ArgumentParser(prog="mirror")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("size")
    s.add_argument("url")
    args = p.parse_args(argv)
    if args.cmd == "size":
        print(head(args.url))
    return 0


if __name__ == "__main__":
    sys.exit(main())
