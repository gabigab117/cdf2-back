import datetime as dt

import pytest
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from tests.accounts.factories import BoardMemberFactory, UserFactory
from tests.events.factories import EventFactory, PracticalInfoFactory, ProgrammeItemFactory

pytestmark = pytest.mark.django_db


def validation_errors(event):
    with pytest.raises(ValidationError) as caught:
        event.full_clean()
    return caught.value.message_dict


def database_refuses(event):
    with pytest.raises(IntegrityError), transaction.atomic():
        event.save()


def test_an_event_cannot_end_before_it_starts():
    """
    Given an event whose end comes before its start
    When it is validated, or written straight to the database
    Then it is refused, with the reason in French
    """
    now = timezone.now()
    event = EventFactory.build(starts_at=now, ends_at=now - dt.timedelta(minutes=1))

    assert validation_errors(event) == {
        NON_FIELD_ERRORS: ["La fin de l’événement ne peut pas précéder son début."]
    }
    database_refuses(event)


def test_an_event_may_have_no_end():
    """
    Given an event with a start and no end
    When it is validated
    Then it is accepted
    """
    EventFactory.build(ends_at=None).full_clean()


def test_coordinates_go_together():
    """
    Given an event with a latitude but no longitude
    When it is validated, or written straight to the database
    Then it is refused: a map needs both
    """
    event = EventFactory.build(latitude=49.42, longitude=None)

    assert validation_errors(event) == {
        NON_FIELD_ERRORS: ["Indiquez la latitude et la longitude, ou aucune des deux."]
    }
    database_refuses(event)


def test_coordinates_stay_on_the_globe():
    """
    Given an event placed beyond the poles and the antimeridian
    When it is validated
    Then both coordinates are refused, each under its field
    """
    event = EventFactory.build(latitude=90.5, longitude=-180.5)

    assert validation_errors(event) == {
        "latitude": ["Assurez-vous que cette valeur est inférieure ou égale à 90."],
        "longitude": ["Assurez-vous que cette valeur est supérieure ou égale à -180."],
    }


def test_an_event_is_not_its_own_previous_edition():
    """
    Given an event
    When it is set as its own previous edition
    Then it is refused, by the validation and by the database
    """
    event = EventFactory()
    event.previous_edition = event

    assert validation_errors(event) == {
        NON_FIELD_ERRORS: ["Un événement ne peut pas être sa propre édition précédente."]
    }
    database_refuses(event)


def test_two_events_cannot_share_an_address():
    """
    Given an event at the address loto-2026
    When another event takes the same address
    Then it is refused, the error located under the address
    And the database refuses it as well
    """
    EventFactory(slug="loto-2026")
    event = EventFactory.build(slug="loto-2026")

    assert validation_errors(event) == {"slug": ["Un autre événement utilise déjà cette adresse."]}
    database_refuses(event)


def test_the_lead_is_an_active_board_member():
    """
    Given an account outside the board and an inactive board member
    When either is set as the lead of an event
    Then the event is refused
    And a board member is accepted
    """
    for account in (UserFactory(), BoardMemberFactory(is_active=False)):
        event = EventFactory.build(lead=account)
        assert validation_errors(event) == {"lead": ["Choisissez un membre du bureau."]}

    EventFactory.build(lead=BoardMemberFactory()).full_clean()


def test_the_previous_edition_is_an_existing_event():
    """
    Given no event of id 987654
    When an event names it as its previous edition
    Then the event is refused
    """
    event = EventFactory.build(previous_edition_id=987654)

    assert validation_errors(event) == {"previous_edition": ["Choisissez un événement existant."]}


def test_lines_come_in_display_order():
    """
    Given programme lines and practical info written out of order
    When an event's lines are read
    Then they come in display order
    """
    event = EventFactory()
    ProgrammeItemFactory(event=event, title="Goûter", sort_order=1)
    ProgrammeItemFactory(event=event, title="Accueil", sort_order=0)
    PracticalInfoFactory(event=event, title="Stationnement", sort_order=1)
    PracticalInfoFactory(event=event, title="Accessibilité", sort_order=0)

    assert [item.title for item in event.programme.all()] == ["Accueil", "Goûter"]
    assert [info.title for info in event.practical_infos.all()] == [
        "Accessibilité",
        "Stationnement",
    ]


def test_an_event_and_its_lines_read_as_their_titles():
    """
    Given an event, a programme line at 15:45 and a practical info
    When they are displayed, in the admin or a log
    Then each reads as its title, the line with its time
    """
    item = ProgrammeItemFactory(
        event__title="Halloween des enfants", time=dt.time(15, 45), title="Défilé"
    )
    info = PracticalInfoFactory(title="Enfants accompagnés")

    assert str(item.event) == "Halloween des enfants"
    assert str(item) == "15:45 Défilé"
    assert str(info) == "Enfants accompagnés"
