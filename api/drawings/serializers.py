import uuid

from django.conf import settings
from rest_framework import serializers

from .models import Annotation, Drawing, Project


class AnnotationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField()

    class Meta:
        model = Annotation
        fields = ["id", "kind", "x", "y", "w", "h"]

    def validate(self, attrs):
        # The DB has check constraints for these too; catching them here turns
        # a 500 into a readable 400.
        for axis, size in (("x", "w"), ("y", "h")):
            origin, extent = attrs[axis], attrs[size]
            if not 0 <= origin <= 1:
                raise serializers.ValidationError({axis: "Must be between 0 and 1."})
            if not 0 < extent <= 1:
                raise serializers.ValidationError({size: "Must be greater than 0 and at most 1."})
            if origin + extent > 1.0001:  # tolerate float noise from the client
                raise serializers.ValidationError(
                    {size: f"Rectangle extends past the page edge ({axis} + {size} > 1)."}
                )
        return attrs


class DrawingSerializer(serializers.ModelSerializer):
    annotations = AnnotationSerializer(many=True, read_only=True)

    class Meta:
        model = Drawing
        fields = ["id", "page_number", "annotations"]


class ProjectListSerializer(serializers.ModelSerializer):
    """The dashboard card: enough to render a folder, nothing more."""

    page_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Project
        fields = ["id", "name", "filename", "page_count", "size_bytes", "created_at", "updated_at"]


class ProjectDetailSerializer(serializers.ModelSerializer):
    """The viewer bootstrap: everything needed to open a folder in one trip."""

    drawings = DrawingSerializer(many=True, read_only=True)
    page_count = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "filename",
            "page_count",
            "size_bytes",
            "created_at",
            "updated_at",
            "drawings",
        ]

    def get_page_count(self, project) -> int:
        # Derived, never stored — a column could only ever drift from the rows.
        return project.drawings.count()


class UploadTicketRequestSerializer(serializers.Serializer):
    filename = serializers.CharField(max_length=255)
    size_bytes = serializers.IntegerField(min_value=1)

    def validate_filename(self, value):
        if not value.lower().endswith(".pdf"):
            raise serializers.ValidationError("Only PDF files are supported.")
        return value

    def validate_size_bytes(self, value):
        if value > settings.MAX_UPLOAD_BYTES:
            limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
            raise serializers.ValidationError(f"Files must be {limit_mb} MB or smaller.")
        return value


class ProjectCreateSerializer(serializers.Serializer):
    """Create the folder and all of its drawings in one call.

    The client supplies the project id so a retried request cannot produce two
    folders, and the page count so the server never has to parse the PDF.
    """

    id = serializers.UUIDField(required=False, default=uuid.uuid4)
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    filename = serializers.CharField(max_length=255)
    storage_path = serializers.CharField(max_length=512)
    size_bytes = serializers.IntegerField(min_value=0)
    page_count = serializers.IntegerField(min_value=1, max_value=2000)


class AnnotationSaveSerializer(serializers.Serializer):
    drawing_id = serializers.UUIDField()
    annotations = AnnotationSerializer(many=True)

    def validate_annotations(self, value):
        ids = [item["id"] for item in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Duplicate annotation ids in the payload.")
        return value


class BulkAnnotationSaveSerializer(serializers.Serializer):
    """The Save button: the whole folder's markup in one transaction."""

    drawings = AnnotationSaveSerializer(many=True)

    def validate_drawings(self, value):
        ids = [item["drawing_id"] for item in value]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("The same drawing appears twice in the payload.")
        return value
