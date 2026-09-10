import uuid

from django.contrib.auth.models import AbstractBaseUser
from django.db import models


class UserManager(models.Manager):
    def get_or_create_from_google(self, *, google_sub, email, name="", picture=""):
        """Look a user up by their Google subject id, creating them if new.

        The subject id is the stable identifier: an email address can be
        reassigned or changed, `sub` cannot.
        """
        user, created = self.get_or_create(
            google_sub=google_sub,
            defaults={
                "email": email,
                "display_name": name,
                "picture_url": picture,
            },
        )
        if not created:
            # Keep the profile fresh, but never touch google_sub.
            changed = []
            for field, value in (
                ("email", email),
                ("display_name", name),
                ("picture_url", picture),
            ):
                if value and getattr(user, field) != value:
                    setattr(user, field, value)
                    changed.append(field)
            if changed:
                user.save(update_fields=changed)
        return user


class User(AbstractBaseUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    google_sub = models.CharField(max_length=255, unique=True, db_index=True)
    display_name = models.CharField(max_length=255, blank=True)
    picture_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Sign-in happens entirely through Google; there is no local password.
    password = None
    last_login = None

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email

    @property
    def is_authenticated(self):
        return True
