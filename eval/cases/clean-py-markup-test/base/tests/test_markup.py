from ui.markup import MarkupError, parse, to_label
import pytest


def test_plain_text_passes():
    assert parse("hello") == "hello"


def test_nested_tags():
    assert parse("<b>a <i>b</i></b>") == "a b"


def test_mismatched_tag_is_rejected():
    with pytest.raises(MarkupError):
        parse("<b>a</i>")


def test_broken_markup_gives_empty_label():
    assert to_label("<b>a") == ""
