from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from events.models import Event


class Station(models.Model):
    """A station of an event, where volunteers stand: the model of the v1 (A13).

    Over-staffing is allowed: a station is complete once enough people stand
    at it, more being welcome.
    """

    event = models.ForeignKey(
        Event, verbose_name="événement", on_delete=models.CASCADE, related_name="stations"
    )
    name = models.CharField("nom", max_length=100)
    description = models.TextField("description", blank=True)
    # The validator places its error under the field; the constraint keeps the
    # rule in the database. full_clean() skips the constraint of a field that
    # already failed, so a member reads a single message.
    required_count = models.PositiveSmallIntegerField(
        "personnes requises", validators=[MinValueValidator(1)]
    )
    # The position the board gives it among the event's stations.
    sort_order = models.PositiveSmallIntegerField("ordre d’affichage")

    class Meta:
        verbose_name = "poste"
        ordering = ["sort_order", "name", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(required_count__gte=1),
                name="station_requires_someone",
                violation_error_message="Il faut au moins une personne à un poste.",
            ),
        ]

    def __str__(self):
        return self.name


class Assignment(models.Model):
    """A volunteer at a station: a name typed by the board, and a role if any.

    Volunteers have no account (A13). Their names are personal data, erased
    two years after the event (A9).
    """

    station = models.ForeignKey(
        Station, verbose_name="poste", on_delete=models.CASCADE, related_name="assignments"
    )
    name = models.CharField("nom", max_length=100)
    # « bière uniquement », « navette frigo ».
    role = models.CharField("rôle", max_length=150, blank=True)

    class Meta:
        verbose_name = "affectation"
        ordering = ["name", "pk"]

    def __str__(self):
        return f"{self.name} ({self.role})" if self.role else self.name
