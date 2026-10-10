import pytest
from django.db import IntegrityError
from django.db.models import RestrictedError

from reservations.models import Reservation, ReservationLine, TicketType
from tests.events.factories import EventFactory
from tests.reservations.factories import TicketTypeFactory, reserve

pytestmark = pytest.mark.django_db


def test_types_reservations_and_lines_read_as_what_they_are():
    """
    Given a type of place and a reservation of two places of it
    When they are shown in a shell or a log
    Then the type reads as its name, the reservation as its person, the line
    as its type and places
    """
    menu = TicketTypeFactory(name="Menu adulte")
    reservation = reserve(menu.event, name="Famille Martin", adulte=(menu, 2))

    assert (str(menu), str(reservation)) == ("Menu adulte", "Famille Martin")
    assert str(reservation.lines.get()) == "Menu adulte : 2"


def test_the_types_of_an_event_come_in_the_boards_order():
    """
    Given three types of an event, two of them at the same position
    When they are read
    Then they come by position, then by name
    """
    event = EventFactory()
    for name, position in [("Menu enfant", 1), ("Menu adulte", 0), ("Assiette", 1)]:
        TicketTypeFactory(event=event, name=name, sort_order=position)

    assert [ticket_type.name for ticket_type in TicketType.objects.all()] == [
        "Menu adulte",
        "Assiette",
        "Menu enfant",
    ]


def test_a_type_in_use_cannot_be_deleted_but_its_event_can():
    """
    Given a type of place used by a reservation
    When the type is deleted
    Then it is refused, the reservation using it
    But deleting its event takes the type, the reservation and its lines along
    """
    menu = TicketTypeFactory()
    reserve(menu.event, adulte=(menu, 2))

    with pytest.raises(RestrictedError):
        menu.delete()

    menu.event.delete()

    assert not TicketType.objects.exists()
    assert not Reservation.objects.exists()
    assert not ReservationLine.objects.exists()


def test_the_database_keeps_one_line_per_type():
    """
    Given a reservation of two places of a type
    When a second line of the same type is saved past the model's checks
    Then the database refuses it
    """
    menu = TicketTypeFactory()
    reservation = reserve(menu.event, adulte=(menu, 2))

    with pytest.raises(IntegrityError):
        ReservationLine.objects.create(reservation=reservation, ticket_type=menu, quantity=1)


def test_the_database_refuses_a_line_of_no_place():
    """
    Given a reservation
    When a line of no place is saved past the model's checks
    Then the database refuses it
    """
    menu = TicketTypeFactory()
    reservation = reserve(menu.event)

    with pytest.raises(IntegrityError):
        ReservationLine.objects.create(reservation=reservation, ticket_type=menu, quantity=0)
