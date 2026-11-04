from slug.core import slugify

def test_basic():
    assert slugify("Hello World") == "hello-world"

def test_strips_edge_dashes():
    assert slugify("  Hello, World!  ") == "hello-world"
