from settings.cors import origin_allowed
from settings.merge import effective


def test_defaults_without_settings():
    assert effective({})["retries"] == 3


def test_project_overrides_a_value():
    s = effective({"settings": {"timeout_s": 10, "allowed_origins": ["https://app.example.com"]}})
    assert s["timeout_s"] == 10
    assert s["retries"] == 3


def test_listed_origin_is_allowed():
    p = {"settings": {"allowed_origins": ["https://app.example.com"]}}
    assert origin_allowed(p, "https://app.example.com")
    assert not origin_allowed(p, "https://evil.example.net")
