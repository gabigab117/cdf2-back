import factory

from reservations.models import Reservation, ReservationLine, TicketType
from tests.events.factories import EventFactory


class TicketTypeFactory(factory.django.DjangoModelFactory):
    """A type of place of an event, such as « Menu adulte »."""

    class Meta:
        model = TicketType

    event = factory.SubFactory(EventFactory)
    name = factory.Sequence(lambda n: f"Menu {n}")
    sort_order = factory.Sequence(lambda n: n)


class ReservationFactory(factory.django.DjangoModelFactory):
    """A reservation for a fictitious person, without places yet."""

    class Meta:
        model = Reservation

    event = factory.SubFactory(EventFactory)
    name = factory.Sequence(lambda n: f"Famille {n}")


def reserve(event, name="Famille Martin", note="", **quantities):
    """A reservation of an event, its places given by type: reserve(event, adulte=(menu, 2))."""
    reservation = ReservationFactory(event=event, name=name, note=note)
    for ticket_type, quantity in quantities.values():
        ReservationLine.objects.create(
            reservation=reservation, ticket_type=ticket_type, quantity=quantity
        )
    return reservation
