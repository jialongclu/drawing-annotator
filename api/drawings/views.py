import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Prefetch
from django.http import FileResponse, HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import Annotation, Drawing, Project
from .permissions import IsOwner
from .serializers import (
    BulkAnnotationSaveSerializer,
    ProjectCreateSerializer,
    ProjectDetailSerializer,
    ProjectListSerializer,
    UploadTicketRequestSerializer,
)
from .storage import (
    LocalStorage,
    StorageError,
    get_storage,
    object_path,
    path_belongs_to,
    verify_local_token,
)

log = logging.getLogger(__name__)


@api_view(["POST"])
def upload_ticket(request):
    """Mint a signed URL the browser can PUT a PDF to.

    Deliberately not nested under a project: the project does not exist yet,
    and requiring one first would leave an orphaned empty folder behind
    whenever an upload failed. Ownership still holds because the server picks
    the path, inside this user's namespace.
    """
    serializer = UploadTicketRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    file_id = uuid.uuid4()
    storage_path = object_path(request.user.id, file_id, serializer.validated_data["filename"])

    try:
        ticket = get_storage().create_upload_ticket(storage_path)
    except StorageError as exc:
        log.exception("Could not create an upload ticket")
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

    return Response(
        {
            "file_id": str(file_id),
            "storage_path": ticket.storage_path,
            "upload_url": ticket.upload_url,
            "method": ticket.method,
            "headers": ticket.headers,
        }
    )


class ProjectViewSet(viewsets.ModelViewSet):
    """Folders, their sheets, and their markup.

    Every drawing and annotation route hangs off a project, so ownership is
    established once when the router resolves the project rather than being
    re-derived (and possibly forgotten) in each handler.
    """

    # IsOwner only implements has_object_permission, so IsAuthenticated must
    # stay in the list. Dropping it would leave the collection routes (list,
    # create) reachable without a token, since object-level checks never run
    # for them.
    permission_classes = [permissions.IsAuthenticated, IsOwner]
    http_method_names = ["get", "post", "patch", "delete", "put", "head", "options"]

    def get_queryset(self):
        # The single line that enforces isolation: another user's project is
        # not merely forbidden, it does not exist as far as this user's
        # queries are concerned.
        queryset = Project.objects.filter(owner=self.request.user)

        if self.action == "list":
            # order_by is explicit because annotate() with an aggregate drops
            # Meta.ordering, which would leave the dashboard listing folders in
            # whatever order the database happened to return them.
            return queryset.annotate(page_count=Count("drawings")).order_by("-updated_at", "id")
        if self.action in {"retrieve", "save_annotations"}:
            return queryset.prefetch_related(
                Prefetch(
                    "drawings",
                    queryset=Drawing.objects.prefetch_related("annotations"),
                )
            )
        return queryset

    def get_serializer_class(self):
        if self.action == "list":
            return ProjectListSerializer
        return ProjectDetailSerializer

    def create(self, request, *args, **kwargs):
        """Register an uploaded PDF as a folder, and fan it out into sheets."""
        serializer = ProjectCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        storage_path = data["storage_path"]
        if not path_belongs_to(storage_path, request.user.id):
            return Response(
                {"detail": "That storage path does not belong to you."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if Project.objects.filter(pk=data["id"]).exists():
            # Client-generated ids make create idempotent; a retry after a
            # dropped response must not produce a second folder.
            project = self.get_queryset().filter(pk=data["id"]).first()
            if project is None:
                return Response(
                    {"detail": "That project id is already taken."},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(ProjectDetailSerializer(project).data, status=status.HTTP_200_OK)

        storage = get_storage()
        try:
            actual_size = storage.stat(storage_path)
        except StorageError as exc:
            log.exception("Could not stat an uploaded object")
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        if actual_size is None:
            return Response(
                {"detail": "No uploaded file was found at that path. Upload it first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            project = Project.objects.create(
                id=data["id"],
                owner=request.user,
                name=(data.get("name") or "").strip() or data["filename"],
                filename=data["filename"],
                storage_path=storage_path,
                size_bytes=actual_size,
            )
            Drawing.objects.bulk_create(
                [
                    Drawing(project=project, page_number=page)
                    for page in range(1, data["page_count"] + 1)
                ]
            )

        project = self.get_queryset().get(pk=project.pk)
        return Response(ProjectDetailSerializer(project).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        return Response(
            {"detail": 'Use PATCH to rename, or PUT on "annotations" to save markup.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def partial_update(self, request, *args, **kwargs):
        """Renaming is the only mutable field; the PDF itself is immutable."""
        project = self.get_object()
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"detail": "A name is required."}, status=status.HTTP_400_BAD_REQUEST)

        project.name = name[:200]
        project.save(update_fields=["name", "updated_at"])
        return Response(ProjectDetailSerializer(project).data)

    def perform_destroy(self, project):
        storage_path = project.storage_path
        project.delete()
        try:
            get_storage().delete(storage_path)
        except StorageError:
            # The row is gone, which is what the user asked for. A stranded
            # object is a quota problem, not a correctness one, and the sweep
            # described in the README collects it.
            log.warning("Deleted project %s but could not remove %s", project.pk, storage_path)

    @action(detail=True, methods=["get"], url_path="source")
    def source(self, request, pk=None):
        """A short-lived signed URL for the project's PDF.

        The browser never holds a durable file URL, so a leaked one stops
        working on its own within minutes.
        """
        project = self.get_object()
        try:
            url = get_storage().signed_read_url(project.storage_path)
        except StorageError as exc:
            log.exception("Could not sign a read URL")
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"url": url, "expires_in": settings.SIGNED_URL_TTL_SECONDS})

    @action(
        detail=True,
        methods=["delete"],
        url_path=r"annotations/(?P<annotation_id>[0-9a-fA-F-]{36})",
    )
    def delete_annotation(self, request, pk=None, annotation_id=None):
        """Delete one rectangle immediately, without waiting for Save.

        Nested under the project so ownership is settled by the router before
        the annotation id is even looked at: `get_object()` already restricted
        us to a project this user owns, and the delete is filtered to drawings
        inside it. An id belonging to somebody else simply matches nothing.

        Idempotent by design — a rectangle that is already gone reports 204
        rather than 404, so a retry after a dropped response is not an error.
        """
        project = self.get_object()

        deleted, _ = Annotation.objects.filter(
            id=annotation_id, drawing__project=project
        ).delete()

        if deleted:
            project.save(update_fields=["updated_at"])

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["put"], url_path="annotations")
    def save_annotations(self, request, pk=None):
        """The Save button.

        Full replace scoped to the drawings named in the payload, in one
        transaction. Ids come from the client, so a retried save converges on
        the same state rather than duplicating rectangles.
        """
        project = self.get_object()

        serializer = BulkAnnotationSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data["drawings"]

        requested_ids = [entry["drawing_id"] for entry in payload]
        owned_ids = set(
            Drawing.objects.filter(project=project, id__in=requested_ids).values_list(
                "id", flat=True
            )
        )
        unknown = [str(i) for i in requested_ids if i not in owned_ids]
        if unknown:
            return Response(
                {"detail": "Some drawings are not part of this project.", "drawing_ids": unknown},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()
        existing = {
            row.id: row for row in Annotation.objects.filter(drawing_id__in=owned_ids)
        }

        incoming_ids = set()
        to_create, to_update, moved = [], [], []

        for entry in payload:
            drawing_id = entry["drawing_id"]
            for item in entry["annotations"]:
                incoming_ids.add(item["id"])
                current = existing.get(item["id"])

                if current is not None and current.drawing_id != drawing_id:
                    # The same rectangle reappearing on a different sheet is a
                    # move, not an edit; recreate it rather than repoint it.
                    moved.append(current.id)
                    current = None

                if current is None:
                    to_create.append(
                        Annotation(
                            id=item["id"],
                            drawing_id=drawing_id,
                            kind=item["kind"],
                            x=item["x"],
                            y=item["y"],
                            w=item["w"],
                            h=item["h"],
                        )
                    )
                else:
                    current.kind = item["kind"]
                    current.x, current.y = item["x"], item["y"]
                    current.w, current.h = item["w"], item["h"]
                    current.updated_at = now
                    to_update.append(current)

        with transaction.atomic():
            stale = [
                row_id
                for row_id in existing
                if row_id not in incoming_ids or row_id in moved
            ]
            if stale:
                Annotation.objects.filter(id__in=stale).delete()
            if to_update:
                Annotation.objects.bulk_update(
                    to_update, ["kind", "x", "y", "w", "h", "updated_at"]
                )
            if to_create:
                Annotation.objects.bulk_create(to_create)

            project.save(update_fields=["updated_at"])

        project = self.get_queryset().get(pk=project.pk)
        return Response(ProjectDetailSerializer(project).data)


# ---------------------------------------------------------------------------
# Local storage backend endpoint (development only)
# ---------------------------------------------------------------------------


@csrf_exempt
def local_storage_object(request):
    """Serve and accept objects for the on-disk storage backend.

    Authorization is the HMAC-signed, expiring token in the query string.
    """
    storage_path = request.GET.get("path", "")
    token = request.GET.get("token", "")
    mode = "write" if request.method in {"PUT", "POST"} else "read"

    if not verify_local_token(token, storage_path=storage_path, mode=mode):
        return HttpResponseForbidden("Invalid or expired storage token.")

    storage = LocalStorage()

    if mode == "write":
        try:
            storage.write(storage_path, request.body)
        except StorageError as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        return HttpResponse(status=200)

    try:
        data = storage.read(storage_path)
    except (FileNotFoundError, StorageError):
        return JsonResponse({"detail": "Not found."}, status=404)

    response = FileResponse(iter([data]), content_type="application/pdf")
    response["Content-Length"] = str(len(data))
    return response
