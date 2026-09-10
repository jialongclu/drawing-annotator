"""Object storage for the PDFs.

Files live under `api/.localstorage`, reachable only through short-lived
HMAC-signed URLs that this same Django process also serves. Unlike a real
object store, both the signed URL and the PUT/GET against it are handled by
Django — there is nothing else to hand the upload to.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.urls import reverse


class StorageError(Exception):
    """Raised when the object store rejects or cannot answer a request."""


@dataclass(frozen=True)
class UploadTicket:
    storage_path: str
    upload_url: str
    method: str
    headers: dict


def object_path(user_id, file_id, filename: str) -> str:
    """Namespace every object under its owner.

    The path is chosen by the server, never by the client, so the prefix is a
    trustworthy ownership claim that we re-check on the way back in.
    """
    suffix = Path(filename).suffix.lower()
    if suffix != ".pdf":
        suffix = ".pdf"
    return f"users/{user_id}/{file_id}{suffix}"


def path_belongs_to(storage_path: str, user_id) -> bool:
    return storage_path.startswith(f"users/{user_id}/") and ".." not in storage_path


# ---------------------------------------------------------------------------
# Local disk
# ---------------------------------------------------------------------------


def _sign(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
    digest = hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{digest}"


def verify_local_token(token: str, *, storage_path: str, mode: str) -> bool:
    try:
        raw, digest = token.rsplit(".", 1)
    except ValueError:
        return False

    expected = hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        return False

    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except (ValueError, TypeError):
        return False

    return (
        payload.get("path") == storage_path
        and payload.get("mode") == mode
        and payload.get("exp", 0) > time.time()
    )


class LocalStorage:
    backend = "local"

    @property
    def root(self) -> Path:
        return Path(settings.LOCAL_STORAGE_ROOT)

    def _absolute(self, storage_path: str) -> Path:
        target = (self.root / storage_path).resolve()
        if not str(target).startswith(str(self.root.resolve())):
            raise StorageError("Refusing to touch a path outside the storage root.")
        return target

    def _url(self, storage_path: str, mode: str) -> str:
        token = _sign(
            {
                "path": storage_path,
                "mode": mode,
                "exp": time.time() + settings.SIGNED_URL_TTL_SECONDS,
            }
        )
        return f"{reverse('local-storage-object')}?path={storage_path}&token={token}"

    def create_upload_ticket(self, storage_path: str) -> UploadTicket:
        return UploadTicket(
            storage_path=storage_path,
            upload_url=self._url(storage_path, "write"),
            method="PUT",
            headers={"content-type": "application/pdf"},
        )

    def signed_read_url(self, storage_path: str) -> str:
        return self._url(storage_path, "read")

    def stat(self, storage_path: str) -> int | None:
        target = self._absolute(storage_path)
        return target.stat().st_size if target.exists() else None

    def write(self, storage_path: str, data: bytes) -> None:
        target = self._absolute(storage_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read(self, storage_path: str) -> bytes:
        return self._absolute(storage_path).read_bytes()

    def delete(self, storage_path: str) -> None:
        target = self._absolute(storage_path)
        if target.exists():
            target.unlink()


def get_storage():
    return LocalStorage()
