from django.urls import path

from . import views

urlpatterns = [
    path("auth/google/", views.google_sign_in, name="auth-google"),
    path("auth/dev/", views.dev_sign_in, name="auth-dev"),
    path("auth/refresh/", views.refresh, name="auth-refresh"),
    path("auth/logout/", views.logout, name="auth-logout"),
    path("me/", views.me, name="me"),
]
