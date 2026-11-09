import re

import pytest

from ui.markup import parse
from ui.strings import FR

# Links are checked by the link checker, so drop them here.
LINK = re.compile(r"</?a\b[^>]*>")


@pytest.mark.parametrize("key", sorted(FR))
def test_every_string_parses(key):
    assert parse(LINK.sub("", FR[key]))
