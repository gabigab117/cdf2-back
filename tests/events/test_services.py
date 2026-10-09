from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError

from events.models import Event, EventCategory, PracticalInfo, PracticalInfoIcon, ProgrammeItem
from events.schemas import EventIn
from events.services.events import create_event, delete_event, update_event
from tests.accounts.factories import BoardMemberFactory, UserFactory
from tests.events.factories import EventFactory, event_payload

pytestmark = pytest.mark.django_db


def data(**changes):
    return EventIn.model_validate(event_payload(**changes))


def validation_errors(write, *args):
    with pytest.raises(ValidationError) as caught:
        write(*args)
    return caught.value.message_dict


def programme_of(event):
    return [(item.sort_order, item.title) for item in event.programme.all()]


# Writing an event


def test_a_new_event_is_recorded_with_its_lines_in_order():
    """
    Given an event with two programme lines and one practical info
    When the board records it
    Then the event is saved with its lines, in the order written
    """
    event = create_event(data())

    event.refresh_from_db()
    assert event.title == "Halloween des enfants"
    assert event.category == EventCategory.CHILDREN
    assert programme_of(event) == [(0, "Accueil et maquillage"), (1, "Goûter")]
    assert [(info.icon, info.title) for info in event.practical_infos.all()] == [
        (PracticalInfoIcon.PEOPLE, "Enfants accompagnés")
    ]


def test_an_update_replaces_the_lines_whole():
    """
    Given an event with a programme of two lines and a practical info
    When the board rewrites it with one new line and no practical info
    Then the event holds the new line alone, and no practical info
    """
    event = create_event(data())

    update_event(
        event,
        data(
            title="Halloween des petits",
            programme=[{"time": "14:30", "title": "Ouverture", "description": ""}],
            practical_infos=[],
        ),
    )

    event.refresh_from_db()
    assert event.title == "Halloween des petits"
    assert programme_of(event) == [(0, "Ouverture")]
    assert not event.practical_infos.exists()
    assert ProgrammeItem.objects.count() == 1


def test_a_failed_update_leaves_the_event_as_it_was():
    """
    Given an event and its programme
    When its rewrite fails midway, while the practical info is written
    Then nothing of the rewrite remains: neither the title nor the programme
    """
    event = create_event(data())

    with (
        patch.object(PracticalInfo.objects, "bulk_create", side_effect=DatabaseError),
        pytest.raises(DatabaseError),
    ):
        update_event(
            event,
            data(
                title="Halloween des petits",
                programme=[{"time": "14:30", "title": "Ouverture", "description": ""}],
            ),
        )

    event.refresh_from_db()
    assert event.title == "Halloween des enfants"
    assert programme_of(event) == [(0, "Accueil et maquillage"), (1, "Goûter")]


def test_every_error_is_reported_at_once_each_line_under_its_position():
    """
    Given an event without a title, whose second programme line has no title
    and whose practical info has an overlong title
    When the board records it
    Then the three errors are reported together, a line's under its position
    And nothing is written
    """
    errors = validation_errors(
        create_event,
        data(
            title="",
            programme=[
                {"time": "15:00", "title": "Accueil", "description": ""},
                {"time": "17:00", "title": "", "description": ""},
            ],
            practical_infos=[{"icon": "info", "title": "x" * 121, "text": ""}],
        ),
    )

    assert errors == {
        "title": ["Ce champ ne peut pas être vide."],
        "programme.1.title": ["Ce champ ne peut pas être vide."],
        "practical_infos.0.title": [
            "Assurez-vous que cette valeur comporte au plus 120 caractères (actuellement 121)."
        ],
    }
    assert not Event.objects.exists()


# Address of the public page


@pytest.mark.parametrize(
    ("title", "starts_at", "slug"),
    [
        ("Halloween des enfants", "2026-10-31T15:00:00+01:00", "halloween-des-enfants-2026"),
        ("Chasse aux œufs", "2027-03-28T10:30:00+02:00", "chasse-aux-oeufs-2027"),
        ("Loto d’automne", "2026-11-15T13:00:00+01:00", "loto-d-automne-2026"),
        # Already 1 January 2027 in Paris.
        ("Réveillon", "2026-12-31T23:30:00+00:00", "reveillon-2027"),
    ],
)
def test_an_address_is_derived_from_the_title_and_the_year(title, starts_at, slug):
    """
    Given an event recorded without an address
    When the board records it
    Then its address is made of its title and of the year it starts in Paris,
    with French ligatures and apostrophes spelled out
    """
    event = create_event(data(title=title, starts_at=starts_at, ends_at=None))

    assert event.slug == slug


def test_each_edition_of_a_yearly_event_has_its_own_address():
    """
    Given the 2025 edition of « Halloween des enfants »
    When the board records the 2026 edition, under the same title
    Then each edition has its own address
    """
    create_event(data(starts_at="2025-10-31T15:00:00+01:00", ends_at=None))

    event = create_event(data())

    assert event.slug == "halloween-des-enfants-2026"
    assert Event.objects.filter(slug="halloween-des-enfants-2025").exists()


def test_an_address_typed_by_the_board_is_normalised():
    """
    Given an address typed with capitals, accents, spaces and an apostrophe
    When the board records the event
    Then the address is kept, in lower case letters and dashes
    """
    event = create_event(data(slug="Loto Géant d’Automne"))

    assert event.slug == "loto-geant-d-automne"


def test_an_address_already_used_is_refused():
    """
    Given an event at the address halloween-des-enfants-2026
    When the board records another event that would take it
    Then the event is refused, the error under the address
    """
    EventFactory(slug="halloween-des-enfants-2026")

    assert validation_errors(create_event, data()) == {
        "slug": ["Un autre événement utilise déjà cette adresse."]
    }


# Lead


def test_a_lead_being_chosen_must_be_a_board_member():
    """
    Given an account outside the board
    When the board makes it the lead of an event
    Then the event is refused, the error under the lead
    """
    errors = validation_errors(create_event, data(lead=UserFactory().pk))

    assert errors == {"lead": ["Choisissez un membre du bureau."]}


def test_a_lead_who_left_the_board_stays_the_lead_of_their_events():
    """
    Given an event led by a member who has left the board since
    When the board rewrites the event, keeping its lead
    Then the event is saved, with the same lead
    """
    member = BoardMemberFactory()
    event = create_event(data(lead=member.pk))
    member.groups.clear()

    update_event(event, data(lead=member.pk, title="Halloween des petits"))

    event.refresh_from_db()
    assert event.lead == member
    assert event.title == "Halloween des petits"


# Deletion


def test_deleting_an_event_deletes_its_lines_and_unlinks_its_next_edition():
    """
    Given the 2025 and 2026 editions of an event, the second linked to the first
    When the 2025 edition is deleted
    Then its programme and practical info go with it
    And the 2026 edition no longer has a previous edition
    """
    previous = create_event(data(starts_at="2025-10-31T15:00:00+01:00", ends_at=None))
    event = create_event(data(previous_edition=previous.pk))

    delete_event(previous)

    event.refresh_from_db()
    assert event.previous_edition is None
    assert not Event.objects.filter(pk=previous.pk).exists()
    assert ProgrammeItem.objects.filter(event=event).count() == ProgrammeItem.objects.count()
    assert PracticalInfo.objects.filter(event=event).count() == PracticalInfo.objects.count()
