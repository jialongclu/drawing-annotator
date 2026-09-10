"""Folder creation, the upload handshake, and auth token handling."""

import datetime
import uuid

import pytest
from django.utils import timezone

from accounts.tokens import make_refresh_token
from drawings.models import Annotation, Drawing, Project

pytestmark = pytest.mark.django_db


def test_creating_a_project_fans_out_one_drawing_per_page(alice, alice_client, make_project):
    project = make_project(alice_client, alice, pages=42)

    assert project["page_count"] == 42
    assert len(project["drawings"]) == 42
    assert [d["page_number"] for d in project["drawings"]] == list(range(1, 43))
    assert Drawing.objects.filter(project_id=project["id"]).count() == 42


def test_page_count_is_derived_not_stored(alice, alice_client, make_project):
    """It is a serializer field, so it can never drift from the rows."""
    project = make_project(alice_client, alice, pages=5)
    Drawing.objects.filter(project_id=project["id"], page_number=5).delete()

    assert alice_client.get(f"/api/projects/{project['id']}/").data["page_count"] == 4


def test_creating_a_project_twice_with_one_id_makes_one_folder(alice, alice_client, upload_pdf):
    path = upload_pdf(alice)
    body = {
        "id": str(uuid.uuid4()),
        "name": "Retry me",
        "filename": "A-101.pdf",
        "storage_path": path,
        "size_bytes": 74,
        "page_count": 3,
    }

    first = alice_client.post("/api/projects/", body, format="json")
    second = alice_client.post("/api/projects/", body, format="json")

    assert first.status_code == 201
    assert second.status_code == 200
    assert Project.objects.count() == 1
    assert Drawing.objects.count() == 3


def test_creating_a_project_without_uploading_first_is_rejected(alice, alice_client):
    response = alice_client.post(
        "/api/projects/",
        {
            "id": str(uuid.uuid4()),
            "name": "Ghost",
            "filename": "A-101.pdf",
            "storage_path": f"users/{alice.id}/{uuid.uuid4()}.pdf",
            "size_bytes": 100,
            "page_count": 2,
        },
        format="json",
    )

    assert response.status_code == 400
    assert Project.objects.count() == 0


def test_project_name_defaults_to_the_filename(alice, alice_client, upload_pdf):
    path = upload_pdf(alice, "S-204-structural.pdf")

    response = alice_client.post(
        "/api/projects/",
        {
            "id": str(uuid.uuid4()),
            "name": "",
            "filename": "S-204-structural.pdf",
            "storage_path": path,
            "size_bytes": 74,
            "page_count": 1,
        },
        format="json",
    )

    assert response.data["name"] == "S-204-structural.pdf"


def test_upload_ticket_paths_are_namespaced_to_the_caller(alice, alice_client):
    response = alice_client.post(
        "/api/upload-ticket/", {"filename": "A-101.pdf", "size_bytes": 2048}, format="json"
    )

    assert response.status_code == 200
    assert response.data["storage_path"].startswith(f"users/{alice.id}/")
    assert response.data["upload_url"]


def test_upload_ticket_rejects_non_pdfs(alice_client):
    response = alice_client.post(
        "/api/upload-ticket/", {"filename": "sheet.dwg", "size_bytes": 2048}, format="json"
    )

    assert response.status_code == 400


def test_upload_ticket_rejects_oversized_files(alice_client, settings):
    settings.MAX_UPLOAD_BYTES = 1024

    response = alice_client.post(
        "/api/upload-ticket/", {"filename": "huge.pdf", "size_bytes": 99999}, format="json"
    )

    assert response.status_code == 400


def test_deleting_a_project_removes_its_drawings_and_annotations(
    alice, alice_client, make_project
):
    project = make_project(alice_client, alice, pages=2)
    sheet = project["drawings"][0]["id"]
    alice_client.put(
        f"/api/projects/{project['id']}/annotations/",
        {
            "drawings": [
                {
                    "drawing_id": sheet,
                    "annotations": [
                        {"id": str(uuid.uuid4()), "kind": "block", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}
                    ],
                }
            ]
        },
        format="json",
    )

    assert alice_client.delete(f"/api/projects/{project['id']}/").status_code == 204
    assert Project.objects.count() == 0
    assert Drawing.objects.count() == 0
    assert Annotation.objects.count() == 0


def test_source_returns_a_short_lived_url(alice, alice_client, make_project, settings):
    project = make_project(alice_client, alice)

    response = alice_client.get(f"/api/projects/{project['id']}/source/")

    assert response.status_code == 200
    assert response.data["expires_in"] == settings.SIGNED_URL_TTL_SECONDS
    assert "token=" in response.data["url"]


def test_renaming_a_project(alice, alice_client, make_project):
    project = make_project(alice_client, alice)

    response = alice_client.patch(
        f"/api/projects/{project['id']}/", {"name": "Level 3 Redlines"}, format="json"
    )

    assert response.status_code == 200
    assert response.data["name"] == "Level 3 Redlines"


def test_projects_are_listed_newest_first_with_page_counts(alice, alice_client, make_project):
    older = make_project(alice_client, alice, pages=2, name="Older")
    make_project(alice_client, alice, pages=7, name="Newer")

    # Both are created in the same clock tick in a test, so age one explicitly
    # rather than depending on timestamp resolution.
    Project.objects.filter(pk=older["id"]).update(
        updated_at=timezone.now() - datetime.timedelta(hours=1)
    )

    response = alice_client.get("/api/projects/")

    assert [p["name"] for p in response.data] == ["Newer", "Older"]
    assert [p["page_count"] for p in response.data] == [7, 2]


def test_listing_order_is_stable_when_timestamps_tie(alice, alice_client, make_project):
    """Same-tick folders must not shuffle between requests."""
    for index in range(4):
        make_project(alice_client, alice, pages=1, name=f"Folder {index}")
    Project.objects.all().update(updated_at=timezone.now())

    first = [p["id"] for p in alice_client.get("/api/projects/").data]
    second = [p["id"] for p in alice_client.get("/api/projects/").data]

    assert first == second


def test_a_refresh_token_cannot_be_used_as_an_access_token(alice, client):
    """`typ` is checked on decode, so the long-lived token cannot call the API."""
    client.credentials = None
    response = client.get(
        "/api/projects/", HTTP_AUTHORIZATION=f"Bearer {make_refresh_token(alice)}"
    )

    assert response.status_code == 401


def test_me_returns_the_signed_in_user(alice, alice_client):
    response = alice_client.get("/api/me/")

    assert response.status_code == 200
    assert response.data["email"] == "alice@example.com"


def test_dev_sign_in_issues_a_working_session(client, settings):
    settings.ALLOW_DEV_LOGIN = True

    response = client.post(
        "/api/auth/dev/", {"email": "carol@example.com"}, content_type="application/json"
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "carol@example.com"
    assert settings.REFRESH_COOKIE_NAME in response.cookies


def test_dev_sign_in_is_unavailable_when_disabled(client, settings):
    settings.ALLOW_DEV_LOGIN = False

    response = client.post(
        "/api/auth/dev/", {"email": "carol@example.com"}, content_type="application/json"
    )

    assert response.status_code == 404


def test_refresh_without_a_cookie_is_rejected(client):
    assert client.post("/api/auth/refresh/").status_code == 401
