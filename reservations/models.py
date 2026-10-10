from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from events.models import Event


class TicketType(models.Model):
    """A kind of place an event offers, such as « Menu adulte » (D1)."""

    event = models.ForeignKey(
        Event, verbose_name="événement", on_delete=models.CASCADE, related_name="ticket_types"
    )
    name = models.CharField("nom", max_length=100)
    # Its place among the event's types: the order they were added in.
    sort_order = models.PositiveSmallIntegerField("ordre d’affichage")

    class Meta:
        verbose_name = "type de place"
        verbose_name_plural = "types de place"
        ordering = ["sort_order", "name", "pk"]
        constraints = [
            # An expression: Django places its error on the form, not on the name.
            models.UniqueConstraint(
                Lower("name"),
                "event",
                name="ticket_type_unique_name",
                violation_error_message="Ce type de place existe déjà pour cet événement.",
            ),
        ]

    def __str__(self):
        return self.name


class Reservation(models.Model):
    """Places the board reserves for someone: a name, a remark, places by type (D1).

    The name and the remark are personal data, erased three months after the
    event, the totals kept (A9).
    """

    event = models.ForeignKey(
        Event, verbose_name="événement", on_delete=models.CASCADE, related_name="reservations"
    )
    name = models.CharField("nom", max_length=100)
    # « table, placement… »: never a health detail, such as an allergy.
    note = models.CharField("remarque", max_length=255, blank=True)
    created_at = models.DateTimeField("saisie le", auto_now_add=True)

    class Meta:
        verbose_name = "réservation"
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return self.name


class ReservationLine(models.Model):
    """The places of a reservation of one type."""

    reservation = models.ForeignKey(
        Reservation, verbose_name="réservation", on_delete=models.CASCADE, related_name="lines"
    )
    # A type in use cannot be deleted. Its event can, which takes the
    # reservations and their lines along in the same deletion.
    ticket_type = models.ForeignKey(
        TicketType,
        verbose_name="type de place",
        on_delete=models.RESTRICT,
        related_name="lines",
        error_messages={"invalid": "Choisissez un type de place existant."},
    )
    # The validator places its error under the field; the constraint keeps the
    # rule in the database.
    quantity = models.PositiveIntegerField("quantité", validators=[MinValueValidator(1)])

    class Meta:
        verbose_name = "ligne de réservation"
        verbose_name_plural = "lignes de réservation"
        ordering = ["ticket_type__sort_order", "ticket_type__name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["reservation", "ticket_type"],
                name="reservation_line_unique_type",
                violation_error_message="Ce type de place figure déjà dans la réservation.",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="reservation_line_some_places",
                violation_error_message="Indiquez au moins une place.",
            ),
        ]

    def __str__(self):
        return f"{self.ticket_type} : {self.quantity}"

    def clean(self):
        # The type must be one of the event of the reservation, which may not be
        # recorded yet: their events are compared. A type that does not exist is
        # the field's own error.
        try:
            ticket_type = self.ticket_type
        except TicketType.DoesNotExist:
            return
        if ticket_type.event_id != self.reservation.event_id:
            message = "Le type de place n’appartient pas à l’événement de la réservation."
            raise ValidationError({"ticket_type": message})
