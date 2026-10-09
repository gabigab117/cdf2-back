# Imported for its side effect, whatever the order of INSTALLED_APPS: it
# registers the token admins, which are removed below.
import ninja_jwt.token_blacklist.admin  # noqa: F401
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm
from django.utils.translation import gettext_lazy as _
from ninja_jwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from accounts.models import User

# The token admins of ninja-jwt display each refresh token in clear: whoever
# reads one could act as its owner, without a trace. An account's access is cut
# by deactivating it or taking it out of the board, which takes effect at once.
admin.site.unregister([OutstandingToken, BlacklistedToken])


class UserCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ("email",)
        field_classes = {}


class UserChangeForm(BaseUserChangeForm):
    class Meta(BaseUserChangeForm.Meta):
        model = User
        field_classes = {}


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Django's user admin, with the email address in place of the username."""

    form = UserChangeForm
    add_form = UserCreationForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "position")}),
        (
            _("Permissions"),
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    # The groups are set on creation: an account reaches the board space once
    # it belongs to the board group.
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "position",
                    "groups",
                    "usable_password",
                    "password1",
                    "password2",
                ),
            },
        ),
    )
    list_display = ("email", "first_name", "last_name", "position", "is_staff", "is_active")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
