"""Access and refresh tokens.

Two tokens with different jobs and different storage:

* access  — 15 minutes, returned in the response body, held in memory by the
            SPA and sent as `Authorization: Bearer`.
* refresh — 30 days, set as an HttpOnly cookie the JavaScript cannot read.

Both are HS256 JWTs signed with the Django secret. `typ` is checked on every
decode so a refresh token can never be replayed as an access token.
"""

import datetime as dt

import jwt
from django.conf import settings

ALGORITHM = "HS256"


class TokenError(Exception):
    pass


def _encode(*, subject: str, token_type: str, lifetime_seconds: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(subject),
        "typ": token_type,
        "iat": now,
        "exp": now + dt.timedelta(seconds=lifetime_seconds),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def _decode(token: str, *, expected_type: str) -> str:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    if payload.get("typ") != expected_type:
        raise TokenError(f"expected a {expected_type} token")

    subject = payload.get("sub")
    if not subject:
        raise TokenError("token has no subject")
    return subject


def make_access_token(user) -> str:
    return _encode(
        subject=user.id,
        token_type="access",
        lifetime_seconds=settings.ACCESS_TOKEN_LIFETIME_SECONDS,
    )


def make_refresh_token(user) -> str:
    return _encode(
        subject=user.id,
        token_type="refresh",
        lifetime_seconds=settings.REFRESH_TOKEN_LIFETIME_SECONDS,
    )


def read_access_token(token: str) -> str:
    return _decode(token, expected_type="access")


def read_refresh_token(token: str) -> str:
    return _decode(token, expected_type="refresh")


def set_refresh_cookie(response, token: str):
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        token,
        max_age=settings.REFRESH_TOKEN_LIFETIME_SECONDS,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=settings.REFRESH_COOKIE_PATH,
    )
    return response


def clear_refresh_cookie(response):
    # The attributes have to match the ones the cookie was set with, or the
    # browser treats it as a different cookie and leaves the original in place.
    response.delete_cookie(
        settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )
    return response
