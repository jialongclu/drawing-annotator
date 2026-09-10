import logging

from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import User
from .tokens import (
    TokenError,
    clear_refresh_cookie,
    make_access_token,
    make_refresh_token,
    read_refresh_token,
    set_refresh_cookie,
)

log = logging.getLogger(__name__)


def serialize_user(user):
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "picture_url": user.picture_url,
    }


def session_response(user, *, status_code=status.HTTP_200_OK):
    response = Response(
        {"user": serialize_user(user), "access_token": make_access_token(user)},
        status=status_code,
    )
    return set_refresh_cookie(response, make_refresh_token(user))


@api_view(["POST"])
@permission_classes([AllowAny])
def google_sign_in(request):
    """Exchange a Google ID token for a session.

    The ID token's signature, audience, issuer and expiry are all verified
    against Google's published keys before we trust a single field in it.
    """
    credential = request.data.get("id_token") or request.data.get("credential")
    if not credential:
        return Response({"detail": "id_token is required."}, status=status.HTTP_400_BAD_REQUEST)

    if not settings.GOOGLE_CLIENT_ID:
        return Response(
            {
                "detail": (
                    "Google sign-in is not configured on this server. Set GOOGLE_CLIENT_ID "
                    "to the same client id the frontend was built with."
                )
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        claims = google_id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
            # A few seconds of tolerance for clock drift between this machine
            # and Google's, which otherwise fails as "Token used too early".
            clock_skew_in_seconds=10,
        )
    except ValueError as exc:
        message = str(exc)
        if "audience" in message.lower():
            # By far the most common setup mistake: the frontend was built with
            # one client id and the server is checking against another.
            message = (
                "This token was issued for a different Google client id than the server "
                "is configured with. VITE_GOOGLE_CLIENT_ID and GOOGLE_CLIENT_ID must match."
            )
        log.warning("Rejected a Google ID token: %s", exc)
        return Response({"detail": message}, status=status.HTTP_401_UNAUTHORIZED)

    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        return Response({"detail": "Unexpected token issuer."}, status=status.HTTP_401_UNAUTHORIZED)

    if not claims.get("email_verified"):
        return Response(
            {"detail": "This Google account has no verified email address."},
            status=status.HTTP_403_FORBIDDEN,
        )

    user = User.objects.get_or_create_from_google(
        google_sub=claims["sub"],
        email=claims["email"],
        name=claims.get("name", ""),
        picture=claims.get("picture", ""),
    )
    return session_response(user)


@api_view(["POST"])
@permission_classes([AllowAny])
def dev_sign_in(request):
    """Sign in as an arbitrary email without Google. Local development only.

    `ALLOW_DEV_LOGIN` is computed as `DEBUG and ...`, so this cannot be turned
    on in a deployed environment even by setting the environment variable.
    """
    if not settings.ALLOW_DEV_LOGIN:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    email = (request.data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return Response({"detail": "A valid email is required."}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.get_or_create_from_google(
        google_sub=f"dev|{email}",
        email=email,
        name=email.split("@")[0],
    )
    return session_response(user)


@api_view(["POST"])
@permission_classes([AllowAny])
def refresh(request):
    token = request.COOKIES.get(settings.REFRESH_COOKIE_NAME)
    if not token:
        return Response({"detail": "No refresh cookie."}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        user_id = read_refresh_token(token)
        user = User.objects.get(pk=user_id)
    except (TokenError, User.DoesNotExist, ValueError):
        # A stale or forged cookie should not linger in the browser.
        response = Response({"detail": "Invalid refresh token."}, status=status.HTTP_401_UNAUTHORIZED)
        return clear_refresh_cookie(response)

    return session_response(user)


@api_view(["POST"])
@permission_classes([AllowAny])
def logout(request):
    return clear_refresh_cookie(Response(status=status.HTTP_204_NO_CONTENT))


@api_view(["GET"])
def me(request):
    return Response(serialize_user(request.user))
