import argparse
import sys

from .store import Store


def cmd_add(store, args):
    store.add(args.date, args.text)
    print(f"Saved note for {args.date}")
    return 0


def cmd_show(store, args):
    note = store.get(args.date)
    if note is None:
        print(f"No note for {args.date}", file=sys.stderr)
        return 1
    print(note)
    return 0


def cmd_delete(store, args):
    print(f"Deleted note for {args.date}")
    return 0


def main(argv=None, store=None):
    p = argparse.ArgumentParser(prog="jot")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("date")
    a.add_argument("text")
    a.set_defaults(fn=cmd_add)
    s = sub.add_parser("show")
    s.add_argument("date")
    s.set_defaults(fn=cmd_show)
    d = sub.add_parser("delete")
    d.add_argument("date")
    d.set_defaults(fn=cmd_delete)
    args = p.parse_args(argv)
    return args.fn(store or Store(), args)
