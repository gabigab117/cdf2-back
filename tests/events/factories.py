import datetime as dt

import factory
from django.utils import timezone

from events.models import Event, EventCategory, PracticalInfo, PracticalInfoIcon, ProgrammeItem


class EventFactory(factory.django.DjangoModelFactory):
    """An unpublished event, a month ahead."""

    class Meta:
        model = Event

    title = factory.Sequence(lambda n: f"Loto d’automne {n}")
    slug = factory.Sequence(lambda n: f"loto-d-automne-{n}")
    category = EventCategory.GAMES
    starts_at = factory.LazyFunction(lambda: timezone.now() + dt.timedelta(days=30))
    venue_name = "Salle des fêtes"


class ProgrammeItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProgrammeItem

    event = factory.SubFactory(EventFactory)
    time = dt.time(15)
    title = factory.Sequence(lambda n: f"Animation {n}")
    sort_order = factory.Sequence(lambda n: n)


class PracticalInfoFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PracticalInfo

    event = factory.SubFactory(EventFactory)
    icon = PracticalInfoIcon.PARKING
    title = factory.Sequence(lambda n: f"Information {n}")
    sort_order = factory.Sequence(lambda n: n)


def event_payload(**changes):
    """The JSON body of an event, whole, as the board's form sends it."""
    return {
        "title": "Halloween des enfants",
        "slug": "",
        "category": "children",
        "starts_at": "2026-10-31T15:00:00+01:00",
        "ends_at": "2026-10-31T18:30:00+01:00",
        "start_label": "",
        "venue_name": "Salle des fêtes",
        "venue_address": "1 place de la Mairie",
        "latitude": None,
        "longitude": None,
        "price_label": "Gratuit",
        "price_detail": "Goûter offert par le comité",
        "summary": "Défilé costumé, chasse aux bonbons, puis goûter.",
        "published": False,
        "lead": None,
        "previous_edition": None,
        "programme": [
            {"time": "15:00", "title": "Accueil et maquillage", "description": "Salle des fêtes."},
            {"time": "17:00", "title": "Goûter", "description": ""},
        ],
        "practical_infos": [
            {"icon": "people", "title": "Enfants accompagnés", "text": "Un adulte par groupe."},
        ],
    } | changes
