from django.conf import settings
from django.db import models
from django.db.models import Q

from events.models import Event


# Named after its model rather than nested in it: the OpenAPI document names an
# enumeration after its class (see events/models.py).
class NoteTag(models.TextChoices):
    MINUTES = "minutes", "Compte rendu"
    BUDGET = "budget", "Budget"
    LOGISTICS = "logistics", "Logistique"


class Note(models.Model):
    """A note of the board, the memory of its work (A11): on an event, or general.

    A reply answers a note, one level deep: it takes its context from its note,
    and has neither event, tag nor pin of its own.
    """

    # No event: a general note, such as the shopping list sent to the board.
    event = models.ForeignKey(
        Event,
        verbose_name="événement",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notes",
        error_messages={"invalid": "Choisissez un événement existant."},
    )
    # A deleted account leaves its notes behind, without a name.
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="auteur",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_notes",
    )
    text = models.TextField("texte")
    # Null rather than empty when the note has no tag: the API gives a tag as
    # one of its choices or nothing, and an empty text is neither. The schemas
    # never let an empty text in, so "no tag" has a single value.
    tag = models.CharField(  # noqa: DJ001
        "étiquette", max_length=20, choices=NoteTag.choices, null=True, blank=True
    )
    pinned = models.BooleanField("épinglée", default=False)
    parent = models.ForeignKey(
        "self",
        verbose_name="note",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
        # A reply answers a note, never another reply.
        limit_choices_to={"parent__isnull": True},
        error_messages={"invalid": "On ne répond qu’à une note, pas à une réponse."},
    )
    created_at = models.DateTimeField("écrite le", auto_now_add=True)
    updated_at = models.DateTimeField("modifiée le", auto_now=True)

    class Meta:
        verbose_name = "note du bureau"
        verbose_name_plural = "notes du bureau"
        constraints = [
            models.CheckConstraint(
                condition=Q(parent__isnull=True)
                | Q(event__isnull=True, tag__isnull=True, pinned=False),
                name="note_reply_without_event_tag_or_pin",
                violation_error_message="Une réponse n’a ni événement, ni étiquette, ni épingle.",
            ),
        ]

    def __str__(self):
        return self.text[:60]
