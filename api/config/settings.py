"""Django settings for the drawing annotator API.

Designed to run in two places without code changes:

* locally, with no external services  -> SQLite + on-disk object storage
* on Render                           -> Render Postgres + on-disk object storage

On Render this is one long-lived web service that serves both the API and the
built SPA. Keeping them on a single origin is what lets the refresh token stay
a SameSite=Strict cookie with no CORS involved.

Everything that differs is driven by environment variables, and every one of
them has a safe local default except the secrets, which are required in
production and refused in production if left at their development value.
"""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------

RENDER_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")

DEBUG = env_bool("DJANGO_DEBUG", default=not RENDER_HOSTNAME)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-development-key-do-not-deploy")

if not DEBUG and SECRET_KEY == "insecure-development-key-do-not-deploy":
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

# Render injects its own hostname; anything else has to be named explicitly
# rather than waved through with a wildcard.
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()]
if RENDER_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_HOSTNAME)
if DEBUG:
    ALLOWED_HOSTS += ["localhost", "127.0.0.1", "[::1]", "testserver"]

CSRF_TRUSTED_ORIGINS = [
    origin
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if RENDER_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_HOSTNAME}")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "accounts",
    "drawings",
]

# No CsrfViewMiddleware, deliberately. This is a pure JSON API authenticated by
# a Bearer token in a header, which a cross-site form cannot set. The one
# cookie in play is the refresh token, and it is SameSite=Strict, so a
# cross-site POST to /api/auth/refresh/ never carries it.
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Serves the built SPA and its hashed assets straight from the web service,
    # which is what keeps the API and the app on one origin.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

X_FRAME_OPTIONS = "DENY"

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = []

AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

USE_TZ = True
TIME_ZONE = "UTC"

# The Vite build lands in web/dist; WhiteNoise serves it and index.html is the
# fallback for client-side routes.
SPA_DIST = Path(os.environ.get("SPA_DIST", BASE_DIR.parent / "web" / "dist"))
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# WhiteNoise warns on every request if this is missing, which it is before the
# first collectstatic — including during tests.
STATIC_ROOT.mkdir(parents=True, exist_ok=True)
STATICFILES_DIRS = [SPA_DIST / "assets"] if (SPA_DIST / "assets").is_dir() else []
WHITENOISE_ROOT = SPA_DIST if SPA_DIST.is_dir() else None
WHITENOISE_INDEX_FILE = True

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
        if not DEBUG
        else "django.contrib.staticfiles.storage.StaticFilesStorage"
    },
}


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

if os.environ.get("DATABASE_URL"):
    DATABASES = {
        "default": dj_database_url.config(
            # Render runs one long-lived process, so connections are worth
            # reusing across requests rather than reopening every time.
            conn_max_age=int(os.environ.get("CONN_MAX_AGE", 600)),
            conn_health_checks=True,  # a pooler may drop an idle connection
            ssl_require=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# --------------------------------------------------------------------------
# DRF
# --------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.BearerJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": (
        [
            "rest_framework.renderers.JSONRenderer",
            "rest_framework.renderers.BrowsableAPIRenderer",
        ]
        if DEBUG
        else ["rest_framework.renderers.JSONRenderer"]
    ),
    "UNAUTHENTICATED_USER": None,
}


# --------------------------------------------------------------------------
# Auth: Google sign-in and our own JWTs
# --------------------------------------------------------------------------

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

ACCESS_TOKEN_LIFETIME_SECONDS = 15 * 60
REFRESH_TOKEN_LIFETIME_SECONDS = 30 * 24 * 60 * 60
REFRESH_COOKIE_NAME = "annotator_refresh"
REFRESH_COOKIE_PATH = "/api/auth"

# Strict is right in production, where the SPA and the API share an origin.
# It is also why a cross-origin local setup needs `SameSite=None`: a Strict
# cookie is simply not attached to a cross-site fetch, so /auth/refresh/ would
# receive nothing and every reload would look like a logout.
REFRESH_COOKIE_SAMESITE = os.environ.get("REFRESH_COOKIE_SAMESITE", "Strict").capitalize()
REFRESH_COOKIE_SECURE = env_bool("REFRESH_COOKIE_SECURE", default=not DEBUG)

if REFRESH_COOKIE_SAMESITE not in {"Strict", "Lax", "None"}:
    raise RuntimeError("REFRESH_COOKIE_SAMESITE must be one of Strict, Lax, None.")

if REFRESH_COOKIE_SAMESITE == "None" and not REFRESH_COOKIE_SECURE:
    # Browsers drop a SameSite=None cookie that is not Secure, silently. Fail
    # here instead, where the message can say why.
    raise RuntimeError(
        "REFRESH_COOKIE_SAMESITE=None requires REFRESH_COOKIE_SECURE=1 "
        "(browsers reject the cookie otherwise). Over plain http this only "
        "works on localhost, which browsers treat as a secure context."
    )

# Escape hatch for running the whole app with no Google credentials. It mints a
# session for an arbitrary email, so it is hard-gated on DEBUG and can never be
# switched on in a deployed environment.
ALLOW_DEV_LOGIN = DEBUG and env_bool("ALLOW_DEV_LOGIN", default=True)


# --------------------------------------------------------------------------
# Object storage
# --------------------------------------------------------------------------
#
# On-disk storage, both locally and on Render. Render's free web service has
# no persistent disk, so anything written here does not survive a deploy or
# restart — acceptable for this project, not for a real production workload.

STORAGE_BACKEND = "local"
LOCAL_STORAGE_ROOT = Path(os.environ.get("LOCAL_STORAGE_ROOT", BASE_DIR / ".localstorage"))

SIGNED_URL_TTL_SECONDS = 300
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 100 * 1024 * 1024))

# The local storage backend's PUT handler reads the whole body via
# request.body, which Django refuses above DATA_UPLOAD_MAX_MEMORY_SIZE
# (default ~2.5 MB) regardless of MAX_UPLOAD_BYTES. Keep the two in step, or
# every drawing set past 2.5 MB fails with RequestDataTooBig.
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES


# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
#
# In production there is no cross-origin traffic at all: one Render service
# serves both the SPA and the API. Locally the recommended setup is the same
# shape — Vite proxies /api to Django, so the browser still sees one origin
# and none of this applies.
#
# This exists for the other local setup, where the SPA calls Django directly
# on :8000. `localhost:5173` and `127.0.0.1:5173` are different origins to a
# browser, and Vite quietly moves to :5174 when :5173 is taken, so pinning a
# literal list is a reliable way to produce a confusing CORS failure. In DEBUG
# we accept any loopback port instead.

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if origin.strip()
]

# Always defined, never conditionally: a setting that exists only on some code
# paths is one stale import away from leaking the development allowance into a
# deployed service.
CORS_ALLOWED_ORIGIN_REGEXES = (
    [r"^http://(localhost|127\.0\.0\.1)(:\d+)?$"] if DEBUG else []
)

# Django's default (`same-origin`) severs window.opener the moment this page
# opens a cross-origin popup — which is exactly how Google's "Sign in with
# Google" button delivers its credential back. Invisible locally, where Vite
# serves index.html and never sends this header at all; only shows up once
# WhiteNoise starts serving the SPA itself, here and on Render.
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"

if not DEBUG:
    # Render terminates TLS at its edge and forwards the original scheme.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", default=True)

    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SESSION_COOKIE_SECURE = True
