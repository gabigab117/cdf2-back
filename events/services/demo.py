"""The fictitious events of the mockup, which the preproduction shows (`seed_demo`)."""

import datetime as dt
from dataclasses import dataclass, field
from operator import attrgetter

from django.db import transaction
from django.utils import timezone

from events.models import Event, EventCategory, PracticalInfoIcon
from events.schemas import EventIn
from events.services.events import create_event, event_slug, update_event


@dataclass(frozen=True)
class DemoEvent:
    """An event of the mockup, held on the same day every year."""

    title: str
    month: int
    day: int
    # On its next day, today included, or on its last day before today.
    to_come: bool
    starts: dt.time
    ends: dt.time | None
    # The other fields of EventIn, over the defaults of _DEFAULTS.
    fields: dict[str, object] = field(default_factory=dict)


_DEFAULTS: dict[str, object] = {
    "slug": "",
    "start_label": "",
    "venue_address": "",
    "latitude": None,
    "longitude": None,
    "price_label": "",
    "price_detail": "",
    "summary": "",
    "programme": [],
    "practical_infos": [],
}

_HALL = {"venue_name": "Salle des fêtes", "venue_address": "1 place de la Mairie"}
_EGG_HUNT = {
    "category": EventCategory.CHILDREN,
    "venue_name": "Parc de la mairie",
    "venue_address": "Rue de la Mairie",
    "price_label": "Gratuit",
    "summary": "Les enfants cherchent les œufs cachés dans le parc, puis chocolat chaud pour tous.",
    "practical_infos": [
        {
            "icon": PracticalInfoIcon.PEOPLE,
            "title": "Jusqu’à 10 ans",
            "text": "Les plus petits cherchent dans un coin du parc rien que pour eux.",
        },
    ],
}

DEMO_EVENTS = [
    DemoEvent(
        "Halloween des enfants",
        month=10,
        day=31,
        to_come=True,
        starts=dt.time(15),
        ends=dt.time(18, 30),
        fields=_HALL
        | {
            "category": EventCategory.CHILDREN,
            # Fictitious, near the geographic centre of France.
            "latitude": 46.5397,
            "longitude": 2.43,
            "price_label": "Gratuit",
            "price_detail": "Goûter offert par le comité",
            "summary": (
                "Défilé costumé dans les rues du bourg, chasse aux bonbons chez les habitants, "
                "puis goûter et concours de costumes à la salle des fêtes."
            ),
            "programme": [
                {
                    "time": dt.time(15),
                    "title": "Accueil et maquillage",
                    "description": "Salle des fêtes. Maquillage par les bénévoles et coin photo.",
                },
                {
                    "time": dt.time(15, 45),
                    "title": "Défilé et chasse aux bonbons",
                    "description": (
                        "Départ de la salle des fêtes, retour par la place de l’église. Les "
                        "habitants qui participent affichent l’affichette du comité sur leur porte."
                    ),
                },
                {
                    "time": dt.time(17),
                    "title": "Goûter",
                    "description": "Offert par le comité à tous les enfants.",
                },
                {
                    "time": dt.time(17, 45),
                    "title": "Concours de costumes",
                    "description": "Trois catégories : moins de 6 ans, 6 à 10 ans, plus de 10 ans.",
                },
            ],
            "practical_infos": [
                {
                    "icon": PracticalInfoIcon.PEOPLE,
                    "title": "Enfants accompagnés",
                    "text": (
                        "Les enfants restent sous la responsabilité d’un adulte pendant le défilé."
                    ),
                },
                {
                    "icon": PracticalInfoIcon.HOME,
                    "title": "Vous distribuez des bonbons ?",
                    "text": (
                        "Signalez-vous au comité : on vous dépose une affichette pour votre porte."
                    ),
                },
                {
                    "icon": PracticalInfoIcon.PARKING,
                    "title": "Stationnement",
                    "text": (
                        "Parking de la salle des fêtes. "
                        "Le bourg est fermé aux voitures pendant le défilé."
                    ),
                },
            ],
        },
    ),
    DemoEvent(
        "Loto d’automne",
        month=11,
        day=15,
        to_come=True,
        starts=dt.time(13),
        ends=None,
        fields=_HALL
        | {
            "category": EventCategory.GAMES,
            "start_label": "Ouverture",
            "price_label": "3 € le carton",
            "summary": (
                "Bons d’achat, paniers garnis et lots offerts par les commerçants du village."
            ),
            "programme": [
                {
                    "time": dt.time(13),
                    "title": "Ouverture des portes",
                    "description": "Vente des cartons à l’entrée.",
                },
                {"time": dt.time(14), "title": "Premier tirage", "description": ""},
            ],
            "practical_infos": [
                {
                    "icon": PracticalInfoIcon.FOOD,
                    "title": "Buvette",
                    "text": "Boissons, crêpes et gâteaux maison.",
                },
            ],
        },
    ),
    DemoEvent(
        "Marché de Noël",
        month=12,
        day=13,
        to_come=True,
        starts=dt.time(10),
        ends=dt.time(18),
        fields={
            "category": EventCategory.MARKETS,
            "venue_name": "Place de l’église",
            "venue_address": "Place de l’église",
            "price_label": "Entrée libre",
            "summary": "Artisans et producteurs, vin chaud et visite du père Noël l’après-midi.",
            "programme": [
                {"time": dt.time(10), "title": "Ouverture du marché", "description": ""},
                {
                    "time": dt.time(15),
                    "title": "Arrivée du père Noël",
                    "description": "Photos avec les enfants jusqu’à 17 h.",
                },
            ],
        },
    ),
    DemoEvent(
        "Repas des aînés",
        month=1,
        day=17,
        to_come=True,
        starts=dt.time(12),
        ends=None,
        fields=_HALL
        | {
            "category": EventCategory.MEALS,
            "price_label": "Sur invitation",
            "summary": "Le repas offert par le comité aux aînés de la commune, en musique.",
        },
    ),
    DemoEvent(
        "Chasse aux œufs",
        month=3,
        day=28,
        to_come=True,
        starts=dt.time(10, 30),
        ends=None,
        fields=_EGG_HUNT,
    ),
    DemoEvent(
        "Brocante",
        month=9,
        day=13,
        to_come=False,
        starts=dt.time(7),
        ends=dt.time(18),
        fields={
            "category": EventCategory.MARKETS,
            "venue_name": "Rues du bourg",
            "price_label": "Entrée libre",
            "summary": "La brocante du comité, dans les rues du bourg.",
        },
    ),
    DemoEvent(
        "Fête du 14 juillet",
        month=7,
        day=14,
        to_come=False,
        starts=dt.time(19),
        ends=dt.time(23, 30),
        fields={
            "category": EventCategory.FESTIVITIES,
            "venue_name": "Stade municipal",
            "price_label": "Gratuit",
            "summary": "Repas champêtre, bal et feu d’artifice.",
        },
    ),
    DemoEvent(
        "Feu de la Saint-Jean",
        month=6,
        day=20,
        to_come=False,
        starts=dt.time(21),
        ends=None,
        fields={
            "category": EventCategory.FESTIVITIES,
            "venue_name": "Pré communal",
            "price_label": "Gratuit",
            "summary": "Le grand feu de la Saint-Jean, avec buvette et musique.",
        },
    ),
    DemoEvent(
        "Chasse aux œufs",
        month=4,
        day=5,
        to_come=False,
        starts=dt.time(10, 30),
        ends=None,
        fields=_EGG_HUNT,
    ),
]


@transaction.atomic
def seed_demo_events(today: dt.date) -> list[Event]:
    """Write the events of the mockup, published, around `today`.

    The events to come are put on their next day, today included, and the past
    ones on their last day before today: the demonstration stays alive from
    one year to the next. An event already written is found by its address and
    rewritten, so a second run adds nothing. A run after one of the days has
    gone by writes that event's next edition, and the earlier one stays past.
    """
    past_editions: dict[str, Event] = {}
    events = []
    # The past events first: an event to come takes the past event of the same
    # title as its previous edition.
    for demo in sorted(DEMO_EVENTS, key=attrgetter("to_come")):
        previous = past_editions.get(demo.title) if demo.to_come else None
        event = _write(_event_in(demo, _day_of(demo, today), previous))
        if not demo.to_come:
            past_editions[demo.title] = event
        events.append(event)
    return events


def _day_of(demo: DemoEvent, today: dt.date) -> dt.date:
    this_year = dt.date(today.year, demo.month, demo.day)
    if demo.to_come:
        return this_year if this_year >= today else this_year.replace(year=today.year + 1)
    return this_year if this_year < today else this_year.replace(year=today.year - 1)


def _event_in(demo: DemoEvent, day: dt.date, previous: Event | None) -> EventIn:
    return EventIn.model_validate(
        _DEFAULTS
        | demo.fields
        | {
            "title": demo.title,
            "starts_at": _in_paris(day, demo.starts),
            "ends_at": None if demo.ends is None else _in_paris(day, demo.ends),
            "published": True,
            "lead": None,
            "previous_edition": previous.pk if previous else None,
        }
    )


def _in_paris(day: dt.date, time: dt.time) -> dt.datetime:
    return timezone.make_aware(dt.datetime.combine(day, time))


def _write(data: EventIn) -> Event:
    event = Event.objects.filter(slug=event_slug(data.title, data.starts_at)).first()
    return update_event(event, data) if event else create_event(data)
