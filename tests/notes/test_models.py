import pytest
from django.core.exceptions import ValidationError

from notes.models import Note, NoteTag
from tests.events.factories import EventFactory
from tests.notes.factories import NoteFactory, ReplyFactory

pytestmark = pytest.mark.django_db


def test_a_note_reads_as_the_start_of_its_text():
    """
    Given a note with a long text
    When it is shown in a shell or a log
    Then it reads as the first sixty characters of its text
    """
    note = NoteFactory(text="Parcours validé : départ de la salle des fêtes, retour par la place.")

    assert str(note) == "Parcours validé : départ de la salle des fêtes, retour par l"


def test_a_reply_cannot_answer_another_reply():
    """
    Given a reply to a note
    When a reply to that reply is checked
    Then it is refused under its note: replies stay one level deep
    """
    first = ReplyFactory()

    with pytest.raises(ValidationError) as error:
        Note(parent=first, author=first.author, text="Et moi aussi.").full_clean()

    assert error.value.message_dict == {
        "parent": ["On ne répond qu’à une note, pas à une réponse."]
    }


@pytest.mark.parametrize("own", ["event", "tag", "pin"])
def test_a_reply_has_no_event_tag_or_pin_of_its_own(own):
    """
    Given a note
    When a reply carrying an event, a tag or a pin is checked
    Then it is refused: a reply takes its context from its note
    """
    note = NoteFactory()
    values = {
        "event": lambda: {"event": EventFactory()},
        "tag": lambda: {"tag": NoteTag.BUDGET},
        "pin": lambda: {"pinned": True},
    }[own]()

    with pytest.raises(ValidationError) as error:
        Note(parent=note, author=note.author, text="D’accord.", **values).full_clean()

    assert error.value.messages == ["Une réponse n’a ni événement, ni étiquette, ni épingle."]


def test_a_deleted_account_leaves_its_notes_without_a_name():
    """
    Given a note and a reply written by the same member
    When the member's account is deleted
    Then the note and the reply stay, without an author
    """
    reply = ReplyFactory()
    note = reply.parent
    note.author = reply.author
    note.save()

    reply.author.delete()

    note.refresh_from_db()
    reply.refresh_from_db()
    assert note.author is None
    assert reply.author is None


def test_a_deleted_event_takes_its_notes_and_their_replies_along():
    """
    Given an event with a note answered once, and a note on another event
    When the event is deleted
    Then its note and the reply are deleted with it, the other note stays
    """
    reply = ReplyFactory()
    other = NoteFactory()

    reply.parent.event.delete()

    assert list(Note.objects.all()) == [other]
