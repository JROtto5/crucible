from gateway import views  # noqa: F401  (registers the routes)
from gateway.proxy import handle


def test_docs_are_public():
    assert handle("/docs", "anon")[0] == 200


def test_admin_is_blocked_at_the_edge():
    for p in ("/admin", "/ADMIN/users", "/internal/metrics"):
        assert handle(p, "anon")[0] == 403
