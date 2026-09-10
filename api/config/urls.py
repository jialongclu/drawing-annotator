from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path, re_path


def health(_request):
    """Render's health check target, and a quick way to see how it is wired."""
    return JsonResponse(
        {
            "status": "ok",
            "storage": settings.STORAGE_BACKEND,
            "debug": settings.DEBUG,
        }
    )


def spa(_request, *_args, **_kwargs):
    """Hand every non-API path to the SPA so client-side routes survive a reload.

    Hashed assets are served by WhiteNoise before this ever runs; this only
    catches real navigations like /projects/<uuid>.
    """
    index = Path(settings.SPA_DIST) / "index.html"
    if not index.is_file():
        raise Http404(
            "The frontend has not been built. Run `npm run build` in web/, "
            "or use the Vite dev server on port 5173."
        )
    return FileResponse(index.open("rb"), content_type="text/html")


urlpatterns = [
    path("api/health/", health, name="health"),
    path("api/", include("accounts.urls")),
    path("api/", include("drawings.urls")),
    # Anything that is not /api/ belongs to the SPA.
    re_path(r"^(?!api/).*$", spa, name="spa"),
]
