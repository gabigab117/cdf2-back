from django.conf import settings
from django.contrib import admin
from django.urls import path

from config.api import api

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/", api.urls),
]
