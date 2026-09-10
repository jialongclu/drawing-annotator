from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("projects", views.ProjectViewSet, basename="project")

urlpatterns = [
    path("upload-ticket/", views.upload_ticket, name="upload-ticket"),
    path("_storage/object", views.local_storage_object, name="local-storage-object"),
    path("", include(router.urls)),
]
