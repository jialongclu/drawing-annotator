"""Bulk save semantics — the other place a bug is expensive.

Save is a full replace scoped to the drawings named in the payload, in one
transaction, keyed on client-generated ids so a retry converges rather than
duplicating.
"""

import uuid

import pytest

from drawings.models import Annotation, Drawing, Project

pytestmark = pytest.mark.django_db


def rect(kind="block", **overrides):
    payload = {"id": str(uuid.uuid4()), "kind": kind, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}
    payload.update(overrides)
    return payload


def save(client, project, drawings):
    return client.put(
        f"/api/projects/{project['id']}/annotations/", {"drawings": drawings}, format="json"
    )


def test_nothing_is_persisted_until_save(alice, alice_client, make_project):
    make_project(alice_client, alice)
    assert Annotation.objects.count() == 0


def test_save_persists_and_reloads_identically(alice, alice_client, make_project):
    project = make_project(alice_client, alice)
    sheet = project["drawings"][0]["id"]
    block = rect("block", x=0.11, y=0.24, w=0.30, h=0.08)
    capture = rect("capture", x=0.52, y=0.61, w=0.18, h=0.05)

    response = save(alice_client, project, [{"drawing_id": sheet, "annotations": [block, capture]}])
    assert response.status_code == 200

    reloaded = alice_client.get(f"/api/projects/{project['id']}/").data
    saved = reloaded["drawings"][0]["annotations"]
    assert len(saved) == 2
    assert {a["kind"] for a in saved} == {"block", "capture"}

    stored = next(a for a in saved if a["kind"] == "block")
    assert (stored["x"], stored["y"], stored["w"], stored["h"]) == (0.11, 0.24, 0.30, 0.08)


def test_repeated_save_is_idempotent(alice, alice_client, make_project):
    """A retry after a dropped response must not duplicate rectangles."""
    project = make_project(alice_client, alice)
    sheet = project["drawings"][0]["id"]
    payload = [{"drawing_id": sheet, "annotations": [rect(), rect("capture")]}]

    save(alice_client, project, payload)
    save(alice_client, project, payload)
    save(alice_client, project, payload)

    assert Annotation.objects.count() == 2


def test_save_deletes_rectangles_left_out_of_the_payload(alice, alice_client, make_project):
    project = make_project(alice_client, alice)
    sheet = project["drawings"][0]["id"]
    keep, remove = rect(), rect("capture")

    save(alice_client, project, [{"drawing_id": sheet, "annotations": [keep, remove]}])
    save(alice_client, project, [{"drawing_id": sheet, "annotations": [keep]}])

    assert list(Annotation.objects.values_list("id", flat=True)) == [uuid.UUID(keep["id"])]


def test_save_updates_an_existing_rectangle_in_place(alice, alice_client, make_project):
    project = make_project(alice_client, alice)
    sheet = project["drawings"][0]["id"]
    original = rect("block", x=0.1, y=0.1, w=0.2, h=0.2)

    save(alice_client, project, [{"drawing_id": sheet, "annotations": [original]}])
    moved = dict(original, x=0.5, y=0.5, kind="capture")
    save(alice_client, project, [{"drawing_id": sheet, "annotations": [moved]}])

    assert Annotation.objects.count() == 1
    stored = Annotation.objects.get()
    assert (stored.x, stored.y, stored.kind) == (0.5, 0.5, "capture")


def test_drawings_absent_from_the_payload_are_untouched(alice, alice_client, make_project):
    project = make_project(alice_client, alice, pages=3)
    first, second = project["drawings"][0]["id"], project["drawings"][1]["id"]

    save(
        alice_client,
        project,
        [
            {"drawing_id": first, "annotations": [rect()]},
            {"drawing_id": second, "annotations": [rect("capture")]},
        ],
    )
    # Save again mentioning only the first sheet.
    save(alice_client, project, [{"drawing_id": first, "annotations": []}])

    assert Annotation.objects.filter(drawing_id=first).count() == 0
    assert Annotation.objects.filter(drawing_id=second).count() == 1


def test_a_rectangle_can_move_between_sheets(alice, alice_client, make_project):
    project = make_project(alice_client, alice, pages=2)
    first, second = project["drawings"][0]["id"], project["drawings"][1]["id"]
    box = rect()

    save(alice_client, project, [{"drawing_id": first, "annotations": [box]}])
    save(
        alice_client,
        project,
        [
            {"drawing_id": first, "annotations": []},
            {"drawing_id": second, "annotations": [box]},
        ],
    )

    assert Annotation.objects.count() == 1
    assert str(Annotation.objects.get().drawing_id) == second


@pytest.mark.parametrize(
    "bad",
    [
        {"x": -0.1},
        {"y": 1.4},
        {"w": 0},
        {"h": -0.2},
        {"x": 0.9, "w": 0.5},  # runs off the right edge
        {"kind": "purple"},
    ],
)
def test_out_of_bounds_rectangles_are_rejected(alice, alice_client, make_project, bad):
    project = make_project(alice_client, alice)
    sheet = project["drawings"][0]["id"]

    response = save(alice_client, project, [{"drawing_id": sheet, "annotations": [rect(**bad)]}])

    assert response.status_code == 400
    assert Annotation.objects.count() == 0


def test_a_failed_save_writes_nothing(alice, alice_client, make_project):
    """One bad rectangle must not leave the folder half-saved."""
    project = make_project(alice_client, alice, pages=2)
    first, second = project["drawings"][0]["id"], project["drawings"][1]["id"]

    response = save(
        alice_client,
        project,
        [
            {"drawing_id": first, "annotations": [rect()]},
            {"drawing_id": second, "annotations": [rect(y=9.0)]},
        ],
    )

    assert response.status_code == 400
    assert Annotation.objects.count() == 0


class TestImmediateDelete:
    """`DELETE /projects/{id}/annotations/{annotationId}/` — the popover button.

    This one endpoint bypasses the save buffer on purpose: clicking Delete
    removes the rectangle there and then.
    """

    def test_deletes_one_rectangle_and_leaves_the_rest(self, alice, alice_client, make_project):
        project = make_project(alice_client, alice)
        sheet = project["drawings"][0]["id"]
        doomed, survivor = rect(), rect("capture")
        save(alice_client, project, [{"drawing_id": sheet, "annotations": [doomed, survivor]}])

        response = alice_client.delete(
            f"/api/projects/{project['id']}/annotations/{doomed['id']}/"
        )

        assert response.status_code == 204
        assert list(Annotation.objects.values_list("id", flat=True)) == [
            uuid.UUID(survivor["id"])
        ]

    def test_the_project_and_its_drawings_survive(self, alice, alice_client, make_project):
        """The endpoint deletes a rectangle, never the folder around it."""
        project = make_project(alice_client, alice, pages=3)
        sheet = project["drawings"][0]["id"]
        box = rect()
        save(alice_client, project, [{"drawing_id": sheet, "annotations": [box]}])

        alice_client.delete(f"/api/projects/{project['id']}/annotations/{box['id']}/")

        assert Project.objects.filter(pk=project["id"]).exists()
        assert Drawing.objects.filter(project_id=project["id"]).count() == 3
        assert alice_client.get(f"/api/projects/{project['id']}/").status_code == 200

    def test_deleting_twice_is_not_an_error(self, alice, alice_client, make_project):
        """Idempotent, so a retry after a dropped response is harmless."""
        project = make_project(alice_client, alice)
        sheet = project["drawings"][0]["id"]
        box = rect()
        save(alice_client, project, [{"drawing_id": sheet, "annotations": [box]}])

        first = alice_client.delete(f"/api/projects/{project['id']}/annotations/{box['id']}/")
        second = alice_client.delete(f"/api/projects/{project['id']}/annotations/{box['id']}/")

        assert first.status_code == 204
        assert second.status_code == 204

    def test_an_unknown_id_touches_nothing(self, alice, alice_client, make_project):
        project = make_project(alice_client, alice)
        sheet = project["drawings"][0]["id"]
        save(alice_client, project, [{"drawing_id": sheet, "annotations": [rect()]}])

        response = alice_client.delete(
            f"/api/projects/{project['id']}/annotations/{uuid.uuid4()}/"
        )

        assert response.status_code == 204
        assert Annotation.objects.count() == 1

    def test_bob_cannot_delete_alices_annotation(
        self, alice, alice_client, bob_client, make_project
    ):
        project = make_project(alice_client, alice)
        sheet = project["drawings"][0]["id"]
        box = rect()
        save(alice_client, project, [{"drawing_id": sheet, "annotations": [box]}])

        response = bob_client.delete(f"/api/projects/{project['id']}/annotations/{box['id']}/")

        assert response.status_code == 404
        assert Annotation.objects.count() == 1

    def test_an_annotation_from_another_project_is_not_reachable(
        self, alice, alice_client, make_project
    ):
        """Even your own annotation is untouchable under the wrong project."""
        first = make_project(alice_client, alice, name="First")
        second = make_project(alice_client, alice, name="Second")
        box = rect()
        save(
            alice_client,
            second,
            [{"drawing_id": second["drawings"][0]["id"], "annotations": [box]}],
        )

        response = alice_client.delete(
            f"/api/projects/{first['id']}/annotations/{box['id']}/"
        )

        assert response.status_code == 204  # nothing matched, nothing happened
        assert Annotation.objects.count() == 1

    def test_anonymous_deletes_are_rejected(self, alice, alice_client, make_project, client):
        project = make_project(alice_client, alice)
        sheet = project["drawings"][0]["id"]
        box = rect()
        save(alice_client, project, [{"drawing_id": sheet, "annotations": [box]}])

        response = client.delete(f"/api/projects/{project['id']}/annotations/{box['id']}/")

        assert response.status_code == 401
        assert Annotation.objects.count() == 1

    def test_a_later_save_does_not_resurrect_it(self, alice, alice_client, make_project):
        """The deleted rectangle must not come back when the buffer is saved."""
        project = make_project(alice_client, alice)
        sheet = project["drawings"][0]["id"]
        doomed, survivor = rect(), rect("capture")
        save(alice_client, project, [{"drawing_id": sheet, "annotations": [doomed, survivor]}])
        alice_client.delete(f"/api/projects/{project['id']}/annotations/{doomed['id']}/")

        # The client saves what it now holds, which no longer includes it.
        save(alice_client, project, [{"drawing_id": sheet, "annotations": [survivor]}])

        assert Annotation.objects.count() == 1


def test_duplicate_annotation_ids_are_rejected(alice, alice_client, make_project):
    project = make_project(alice_client, alice)
    sheet = project["drawings"][0]["id"]
    box = rect()

    response = save(alice_client, project, [{"drawing_id": sheet, "annotations": [box, dict(box)]}])

    assert response.status_code == 400
