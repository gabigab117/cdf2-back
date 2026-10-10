from django.conf import settings
from django.db import models

from accounts.services.roles import BOARD_MEMBERS
from events.models import Event


class Task(models.Model):
    """A task of the board: on an event, or general, until it is done."""

    # No event: a general task. The API allows it for the tasks the meeting
    # reports will bring (phases 4 and 9); the board's screens ask for one.
    event = models.ForeignKey(
        Event,
        verbose_name="événement",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="tasks",
        error_messages={"invalid": "Choisissez un événement existant."},
    )
    title = models.CharField("titre", max_length=200)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="assignée à",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
        limit_choices_to=BOARD_MEMBERS,
        error_messages={"invalid": "Choisissez un membre du bureau."},
    )
    due_date = models.DateField("échéance", null=True, blank=True)
    # Done once this is set: when it was done.
    done_at = models.DateTimeField("faite le", null=True, blank=True)
    # A deleted account leaves its tasks behind, without a name.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créée par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_tasks",
    )

    class Meta:
        verbose_name = "tâche"

    def __str__(self):
        return self.title
