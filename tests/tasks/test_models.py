import pytest

from tasks.models import Task
from tests.tasks.factories import TaskFactory

pytestmark = pytest.mark.django_db


def test_a_task_reads_as_its_title():
    """
    Given a task
    When it is shown in a shell or a log
    Then it reads as its title
    """
    assert str(TaskFactory(title="Demander l’arrêté municipal")) == "Demander l’arrêté municipal"


def test_a_deleted_event_takes_its_tasks_along():
    """
    Given an event with a task, and a task of another event
    When the event is deleted
    Then its task is deleted with it, the other stays
    """
    task = TaskFactory()
    other = TaskFactory()

    task.event.delete()

    assert list(Task.objects.all()) == [other]


def test_a_deleted_account_leaves_its_tasks_without_a_name():
    """
    Given a task created by a member and assigned to them
    When the member's account is deleted
    Then the task stays, assigned to nobody and created by nobody
    """
    task = TaskFactory()
    task.assignee = task.created_by
    task.save()

    task.created_by.delete()

    task.refresh_from_db()
    assert (task.assignee, task.created_by) == (None, None)
