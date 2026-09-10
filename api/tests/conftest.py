import uuid

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tokens import make_access_token
from drawings.storage import LocalStorage, object_path

MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


@pytest.fixture(autouse=True)
def storage_root(settings, tmp_path):
    """Point on-disk storage at a temp dir so tests never touch real files."""
    settings.LOCAL_STORAGE_ROOT = tmp_path / "storage"
    settings.STORAGE_BACKEND = "local"
    return settings.LOCAL_STORAGE_ROOT


def make_user(email):
    return User.objects.create(email=email, google_sub=f"sub|{email}", display_name=email)


def client_for(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_access_token(user)}")
    return client


@pytest.fixture
def alice(db):
    return make_user("alice@example.com")


@pytest.fixture
def bob(db):
    return make_user("bob@example.com")


@pytest.fixture
def alice_client(alice):
    return client_for(alice)


@pytest.fixture
def bob_client(bob):
    return client_for(bob)


@pytest.fixture
def upload_pdf():
    """Put bytes in storage the way a real client would, then hand back the path."""

    def _upload(user, filename="A-101.pdf", data=MINIMAL_PDF):
        file_id = uuid.uuid4()
        path = object_path(user.id, file_id, filename)
        LocalStorage().write(path, data)
        return path

    return _upload


@pytest.fixture
def make_project(upload_pdf):
    """Create a folder with `pages` sheets through the real API."""

    def _make(client, user, *, pages=3, name="Level 2 Redlines", filename="A-101.pdf"):
        path = upload_pdf(user, filename)
        response = client.post(
            "/api/projects/",
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "filename": filename,
                "storage_path": path,
                "size_bytes": len(MINIMAL_PDF),
                "page_count": pages,
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        return response.data

    return _make
