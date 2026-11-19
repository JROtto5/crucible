import sys

from .ranking import rank
from .settings import load_settings


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    settings = load_settings(argv[1]) if len(argv) > 1 else None
    scores = {}
    with open(argv[0]) as fh:
        for line in fh:
            if line.strip():
                name, value = line.split(",")         # ValueError on a line that isn't name,score
                scores[name.strip()] = float(value) if value.strip() else None
    for place, name in enumerate(rank(scores, settings), 1):
        print(f"{place}. {name}: {scores[name]}")


if __name__ == "__main__":
    main()
