"""The requirement that matters most: one user cannot reach another's data.

PRD §14 asks for this to be proven by test rather than by inspection, and for
cross-user access to look like absence (404) rather than refusal (403), so
that project ids cannot be enumerated.
"""

import uuid

import pytest

pytestmark = pytest.mark.django_db


def test_bob_cannot_read_alices_project(alice, alice_client, bob_client, make_project):
    project = make_project(alice_client, alice)

    response = bob_client.get(f"/api/projects/{project['id']}/")

    assert response.status_code == 404


def test_bob_cannot_list_alices_projects(alice, alice_client, bob_client, make_project):
    make_project(alice_client, alice)

    response = bob_client.get("/api/projects/")

    assert response.status_code == 200
    assert response.data == []


def test_bob_cannot_get_a_signed_url_for_alices_pdf(alice, alice_client, bob_client, make_project):
    project = make_project(alice_client, alice)

    response = bob_client.get(f"/api/projects/{project['id']}/source/")

    assert response.status_code == 404


def test_bob_cannot_save_annotations_onto_alices_drawings(
    alice, alice_client, bob_client, make_project
):
    project = make_project(alice_client, alice)
    drawing_id = project["drawings"][0]["id"]

    response = bob_client.put(
        f"/api/projects/{project['id']}/annotations/",
        {
            "drawings": [
                {
                    "drawing_id": drawing_id,
                    "annotations": [
                        {"id": str(uuid.uuid4()), "kind": "block", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}
                    ],
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 404


def test_bob_cannot_rename_or_delete_alices_project(alice, alice_client, bob_client, make_project):
    project = make_project(alice_client, alice)

    assert bob_client.patch(f"/api/projects/{project['id']}/", {"name": "mine now"}, format="json").status_code == 404
    assert bob_client.delete(f"/api/projects/{project['id']}/").status_code == 404
    assert alice_client.get(f"/api/projects/{project['id']}/").status_code == 200


def test_annotations_cannot_be_written_across_projects(alice, alice_client, make_project):
    """Even your own drawing id is rejected under the wrong project."""
    first = make_project(alice_client, alice, name="First")
    second = make_project(alice_client, alice, name="Second")
    foreign_drawing = second["drawings"][0]["id"]

    response = alice_client.put(
        f"/api/projects/{first['id']}/annotations/",
        {
            "drawings": [
                {
                    "drawing_id": foreign_drawing,
                    "annotations": [
                        {"id": str(uuid.uuid4()), "kind": "block", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}
                    ],
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 400
    assert foreign_drawing in response.data["drawing_ids"]


def test_upload_path_from_another_user_is_refused(alice, bob, alice_client, upload_pdf):
    """A storage path is only trusted inside the caller's own namespace."""
    bobs_path = upload_pdf(bob)

    response = alice_client.post(
        "/api/projects/",
        {
            "id": str(uuid.uuid4()),
            "name": "Stolen",
            "filename": "A-101.pdf",
            "storage_path": bobs_path,
            "size_bytes": 100,
            "page_count": 2,
        },
        format="json",
    )

    assert response.status_code == 403


def test_anonymous_requests_are_rejected(client):
    assert client.get("/api/projects/").status_code == 401
    assert client.get("/api/me/").status_code == 401
    assert client.post("/api/upload-ticket/").status_code == 401
