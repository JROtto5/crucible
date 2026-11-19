import sys

from .ranking import rank


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    with open(argv[0]) as fh:
        scores = [float(line) for line in fh if line.strip()]
    for place, i in enumerate(rank(scores), 1):
        print(f"{place}. entry {i}: {scores[i]}")


if __name__ == "__main__":
    main()
