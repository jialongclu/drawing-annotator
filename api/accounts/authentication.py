from rest_framework import authentication, exceptions

from .models import User
from .tokens import TokenError, read_access_token


class BearerJWTAuthentication(authentication.BaseAuthentication):
    """Authenticate `Authorization: Bearer <access token>`."""

    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header:
            return None

        parts = header.split()
        if parts[0] != self.keyword:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Malformed Authorization header.")

        try:
            user_id = read_access_token(parts[1])
        except TokenError as exc:
            raise exceptions.AuthenticationFailed(str(exc)) from exc

        try:
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError) as exc:
            raise exceptions.AuthenticationFailed("User no longer exists.") from exc

        return (user, None)

    def authenticate_header(self, request):
        return self.keyword
