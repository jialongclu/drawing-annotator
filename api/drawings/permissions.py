from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """Object-level ownership.

    This is a backstop. The primary defence is `get_queryset` filtering by
    owner, which makes another user's project a 404 rather than a 403 — a 403
    would confirm the id exists and let someone enumerate them.
    """

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, "owner", None)
        if owner is None and hasattr(obj, "project"):
            owner = obj.project.owner
        return owner == request.user
