import factory

from tasks.models import Task
from tests.accounts.factories import BoardMemberFactory
from tests.events.factories import EventFactory


class TaskFactory(factory.django.DjangoModelFactory):
    """An open task of an event, without assignee or due date."""

    class Meta:
        model = Task

    event = factory.SubFactory(EventFactory)
    title = factory.Sequence(lambda n: f"Valider le devis sono ({n})")
    created_by = factory.SubFactory(BoardMemberFactory)
