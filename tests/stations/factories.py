import factory

from stations.models import Assignment, Station
from tests.events.factories import EventFactory


class StationFactory(factory.django.DjangoModelFactory):
    """A station of an event, requiring two people."""

    class Meta:
        model = Station

    event = factory.SubFactory(EventFactory)
    name = factory.Sequence(lambda n: f"Buvette {n}")
    required_count = 2
    sort_order = factory.Sequence(lambda n: n)


class AssignmentFactory(factory.django.DjangoModelFactory):
    """A fictitious volunteer at a station, without a particular role."""

    class Meta:
        model = Assignment

    station = factory.SubFactory(StationFactory)
    name = factory.Sequence(lambda n: f"Bénévole {n}")
