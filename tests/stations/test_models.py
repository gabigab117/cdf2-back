import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from stations.models import Assignment, Station
from tests.stations.factories import AssignmentFactory, StationFactory

pytestmark = pytest.mark.django_db


def test_a_station_and_a_volunteer_read_as_their_names():
    """
    Given a station, a volunteer with a role and one without
    When they are shown in a shell or a log
    Then the station reads as its name, a volunteer as their name and role
    """
    station = StationFactory(name="Buvette")

    assert str(station) == "Buvette"
    assert str(AssignmentFactory(station=station, name="Alice", role="bière uniquement")) == (
        "Alice (bière uniquement)"
    )
    assert str(AssignmentFactory(station=station, name="Bruno")) == "Bruno"


def test_the_database_refuses_a_station_requiring_nobody():
    """
    Given a station
    When it is saved requiring nobody, past the model's checks
    Then the database refuses it
    """
    station = StationFactory()
    station.required_count = 0

    with pytest.raises(IntegrityError):
        station.save()


def test_a_station_requiring_nobody_is_refused_once_under_its_field():
    """
    Given a station requiring nobody
    When it is checked
    Then it is refused once, under the number of people it requires
    """
    station = StationFactory.build(required_count=0)

    with pytest.raises(ValidationError) as error:
        station.full_clean(exclude={"event"})

    assert error.value.message_dict == {
        "required_count": ["Assurez-vous que cette valeur est supérieure ou égale à 1."]
    }


def test_stations_come_in_the_boards_order_then_by_name_and_volunteers_by_name():
    """
    Given three stations of an event, two of them at the same position
    And three volunteers at a station
    When they are read
    Then the stations come by position then by name, the volunteers by name
    """
    first = StationFactory(name="Frites", sort_order=0)
    StationFactory(event=first.event, name="Caisse", sort_order=1)
    StationFactory(event=first.event, name="BBQ", sort_order=1)
    for name in ["Chloé", "Alice", "Bruno"]:
        AssignmentFactory(station=first, name=name)

    assert [station.name for station in Station.objects.all()] == ["Frites", "BBQ", "Caisse"]
    assert [person.name for person in first.assignments.all()] == ["Alice", "Bruno", "Chloé"]


def test_a_deleted_event_takes_its_stations_and_volunteers_along():
    """
    Given an event with a station and a volunteer, and a station of another event
    When the event is deleted
    Then its station and volunteer are deleted with it, the other station stays
    """
    assignment = AssignmentFactory()
    other = StationFactory()

    assignment.station.event.delete()

    assert list(Station.objects.all()) == [other]
    assert not Assignment.objects.exists()
