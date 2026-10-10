import factory

from notes.models import Note
from tests.accounts.factories import BoardMemberFactory
from tests.events.factories import EventFactory


class NoteFactory(factory.django.DjangoModelFactory):
    """A note on an event, by a board member, without tag or pin."""

    class Meta:
        model = Note

    event = factory.SubFactory(EventFactory)
    author = factory.SubFactory(BoardMemberFactory)
    text = factory.Sequence(lambda n: f"Salle réservée de 13 h à 20 h ({n}).")


class ReplyFactory(factory.django.DjangoModelFactory):
    """A reply to a note: no event, tag or pin of its own."""

    class Meta:
        model = Note

    parent = factory.SubFactory(NoteFactory)
    author = factory.SubFactory(BoardMemberFactory)
    text = factory.Sequence(lambda n: f"Je m’en occupe ({n}).")
