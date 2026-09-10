"""Cross-origin behaviour for local development.

The supported local setup is Vite proxying /api to Django, which is same-origin
and needs none of this. These cover the other one — the SPA calling Django
directly — and, more importantly, guard the production side: the loopback
allowance is DEBUG-only and must never widen a deployed service.
"""

import pytest
from django.conf import settings

pytestmark = pytest.mark.django_db


def preflight(client, origin, path="/api/projects/", method="GET"):
    return client.options(
        path,
        HTTP_ORIGIN=origin,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD=method,
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
    )


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        # Vite moves to the next free port when 5173 is taken. Pinning a literal
        # list is how that turns into a mystifying CORS failure.
        "http://localhost:5174",
        "http://localhost:3000",
        "http://127.0.0.1:8080",
        "http://localhost",
    ],
)
def test_any_loopback_origin_is_allowed_in_debug(client, origin, settings):
    settings.DEBUG = True

    response = preflight(client, origin)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


def test_the_delete_endpoint_survives_preflight(client):
    """A cross-origin DELETE is preflighted; the popover breaks without this."""
    response = preflight(
        client,
        "http://localhost:5173",
        path="/api/projects/00000000-0000-0000-0000-000000000000/annotations/"
        "00000000-0000-0000-0000-000000000000/",
        method="DELETE",
    )

    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.example.com",
        "https://localhost.evil.com",
        "http://notlocalhost:5173",
        "http://127.0.0.1.evil.com",
    ],
)
def test_non_loopback_origins_are_refused_even_in_debug(client, origin):
    """The regex is anchored, so a hostname that merely contains "localhost"
    does not slip through."""
    response = preflight(client, origin)

    assert "access-control-allow-origin" not in response.headers


def test_the_loopback_allowance_is_debug_only():
    """Reading the setting module directly: production must not carry it."""
    import importlib
    import os

    previous = dict(os.environ)
    os.environ.update(
        {
            "DJANGO_DEBUG": "0",
            "DJANGO_SECRET_KEY": "x" * 60,
            "RENDER_EXTERNAL_HOSTNAME": "annotator.onrender.com",
        }
    )
    try:
        module = importlib.reload(importlib.import_module("config.settings"))
        assert getattr(module, "CORS_ALLOWED_ORIGIN_REGEXES", []) == []
        assert module.ALLOWED_HOSTS == ["annotator.onrender.com"]
        assert module.REFRESH_COOKIE_SAMESITE == "Strict"
        assert module.REFRESH_COOKIE_SECURE is True
    finally:
        os.environ.clear()
        os.environ.update(previous)
        importlib.reload(importlib.import_module("config.settings"))


class TestRefreshCookie:
    def test_it_is_httponly_and_scoped_to_the_auth_routes(self, client):
        response = client.post(
            "/api/auth/dev/", {"email": "alice@example.com"}, content_type="application/json"
        )

        cookie = response.cookies[settings.REFRESH_COOKIE_NAME]
        assert cookie["httponly"] is True
        assert cookie["path"] == "/api/auth"
        assert cookie["samesite"] == settings.REFRESH_COOKIE_SAMESITE

    def test_samesite_none_is_honoured_for_cross_origin_development(self, client, settings):
        # A Strict cookie is never attached to a cross-site fetch, so a
        # cross-origin SPA would lose its session on every reload.
        settings.REFRESH_COOKIE_SAMESITE = "None"
        settings.REFRESH_COOKIE_SECURE = True

        response = client.post(
            "/api/auth/dev/", {"email": "alice@example.com"}, content_type="application/json"
        )

        cookie = response.cookies[settings.REFRESH_COOKIE_NAME]
        assert cookie["samesite"] == "None"
        assert cookie["secure"] is True

    def test_logging_out_clears_it_with_matching_attributes(self, client):
        # A delete_cookie whose attributes differ from the original is treated
        # as a different cookie, and the real one stays in the browser.
        client.post(
            "/api/auth/dev/", {"email": "alice@example.com"}, content_type="application/json"
        )

        response = client.post("/api/auth/logout/")

        cookie = response.cookies[settings.REFRESH_COOKIE_NAME]
        assert cookie.value == ""
        assert cookie["path"] == settings.REFRESH_COOKIE_PATH
        assert cookie["samesite"] == settings.REFRESH_COOKIE_SAMESITE
