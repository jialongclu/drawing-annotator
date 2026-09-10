"""Google sign-in.

Google's own verification is not re-tested here — `google-auth` owns the
signature and key handling. What is tested is everything around it: that a
token is never trusted without verification, that the setup mistakes people
actually make produce an actionable message, and that a verified token yields
exactly one user no matter how many times they sign in.
"""

from unittest.mock import patch

import pytest

from accounts.models import User

pytestmark = pytest.mark.django_db

VERIFY = "accounts.views.google_id_token.verify_oauth2_token"


def claims(**overrides):
    payload = {
        "iss": "https://accounts.google.com",
        "sub": "google-subject-1234567890",
        "email": "alice@example.com",
        "email_verified": True,
        "name": "Alice Example",
        "picture": "https://lh3.googleusercontent.com/a/alice",
        "aud": "test-client-id.apps.googleusercontent.com",
    }
    payload.update(overrides)
    return payload


def sign_in(client, credential="fake-id-token", field="id_token"):
    return client.post(
        "/api/auth/google/", {field: credential}, content_type="application/json"
    )


@pytest.fixture(autouse=True)
def configured(settings):
    settings.GOOGLE_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
    return settings


class TestSuccessfulSignIn:
    def test_it_creates_a_user_and_returns_a_session(self, client):
        with patch(VERIFY, return_value=claims()):
            response = sign_in(client)

        assert response.status_code == 200
        body = response.json()
        assert body["user"]["email"] == "alice@example.com"
        assert body["user"]["display_name"] == "Alice Example"
        assert body["access_token"]
        assert "annotator_refresh" in response.cookies

    def test_the_access_token_works_against_the_api(self, client):
        with patch(VERIFY, return_value=claims()):
            token = sign_in(client).json()["access_token"]

        response = client.get("/api/projects/", HTTP_AUTHORIZATION=f"Bearer {token}")

        assert response.status_code == 200

    def test_the_button_may_send_the_field_as_credential(self, client):
        """`@react-oauth/google` hands back `credential`; both names are taken."""
        with patch(VERIFY, return_value=claims()):
            response = sign_in(client, field="credential")

        assert response.status_code == 200

    def test_signing_in_twice_reuses_the_same_user(self, client):
        with patch(VERIFY, return_value=claims()):
            sign_in(client)
            sign_in(client)

        assert User.objects.count() == 1

    def test_the_subject_id_identifies_the_user_not_the_email(self, client):
        """A changed email address must not create a second account."""
        with patch(VERIFY, return_value=claims()):
            sign_in(client)
        with patch(VERIFY, return_value=claims(email="alice.new@example.com")):
            sign_in(client)

        assert User.objects.count() == 1
        assert User.objects.get().email == "alice.new@example.com"

    def test_a_different_google_account_is_a_different_user(self, client):
        with patch(VERIFY, return_value=claims()):
            sign_in(client)
        with patch(VERIFY, return_value=claims(sub="another-subject", email="bob@example.com")):
            sign_in(client)

        assert User.objects.count() == 2


class TestRejection:
    def test_a_missing_credential_is_a_400(self, client):
        response = client.post("/api/auth/google/", {}, content_type="application/json")

        assert response.status_code == 400

    def test_an_unverifiable_token_is_a_401(self, client):
        with patch(VERIFY, side_effect=ValueError("Token expired")):
            response = sign_in(client)

        assert response.status_code == 401
        assert User.objects.count() == 0

    def test_a_mismatched_client_id_explains_itself(self, client):
        """The most common setup mistake deserves more than the raw error."""
        with patch(VERIFY, side_effect=ValueError("Token has wrong audience xyz, expected abc")):
            response = sign_in(client)

        assert response.status_code == 401
        detail = response.json()["detail"]
        assert "VITE_GOOGLE_CLIENT_ID" in detail and "GOOGLE_CLIENT_ID" in detail

    def test_an_unverified_email_is_refused(self, client):
        with patch(VERIFY, return_value=claims(email_verified=False)):
            response = sign_in(client)

        assert response.status_code == 403
        assert User.objects.count() == 0

    def test_an_unexpected_issuer_is_refused(self, client):
        """Verification is told the audience, so the issuer is checked here."""
        with patch(VERIFY, return_value=claims(iss="https://evil.example.com")):
            response = sign_in(client)

        assert response.status_code == 401
        assert User.objects.count() == 0

    def test_an_unconfigured_server_says_so(self, client, settings):
        settings.GOOGLE_CLIENT_ID = ""

        response = sign_in(client)

        assert response.status_code == 503
        assert "GOOGLE_CLIENT_ID" in response.json()["detail"]

    def test_verification_is_given_the_configured_client_id(self, client, configured):
        """The audience must come from settings, never from the token itself."""
        with patch(VERIFY, return_value=claims()) as verify:
            sign_in(client)

        assert verify.call_args.args[2] == configured.GOOGLE_CLIENT_ID
