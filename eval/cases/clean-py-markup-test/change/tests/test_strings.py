import pytest

from ui.markup import parse
from ui.strings import FR


@pytest.mark.parametrize("key", sorted(FR))
def test_every_string_parses(key):
    assert parse(FR[key])
