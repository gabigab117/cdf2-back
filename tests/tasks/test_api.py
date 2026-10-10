import datetime as dt

import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.test import Client
from django.utils import timezone
from ninja_jwt.tokens import AccessToken

from tasks.models import Task
from tests.accounts.factories import BoardMemberFactory, UserFactory
from tests.events.factories import EventFactory
from tests.tasks.factories import TaskFactory

pytestmark = pytest.mark.django_db

TASKS = "/api/board/tasks"

# Every operation on the tasks, the paths of a single task naming any id: a
# refusal comes before the task is looked up.
OPERATIONS = [
    ("get", f"{TASKS}?event=1"),
    ("get", f"{TASKS}/general"),
    ("post", TASKS),
    ("put", f"{TASKS}/1"),
    ("delete", f"{TASKS}/1"),
]


def task_url(task_id):
    return f"{TASKS}/{task_id}"


def send(client, method, path, payload=None):
    return getattr(client, method)(path, payload, content_type="application/json")


def iso(moment):
    """A time as the API writes it: to the millisecond, as Django's JSON does."""
    return DjangoJSONEncoder().default(moment)


def member_json(member):
    return {
        "id": member.id,
        "first_name": member.first_name,
        "last_name": member.last_name,
        "email": member.email,
    }


def listed_titles(client, event):
    return [task["title"] for task in client.get(TASKS, {"event": event.id}).json()["items"]]


def task_payload(event, **changes):
    """The JSON body of a task, whole, as the board's forms send it."""
    return {
        "event": event.id,
        "title": "Valider le devis sono",
        "assignee": None,
        "due_date": None,
        "done": False,
    } | changes


# Access


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_tasks_are_reserved_to_signed_in_members(client, method, path):
    """
    Given a visitor without a session
    When they call any operation on the tasks
    Then they are refused with a 401
    """
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_tasks_are_refused_to_accounts_outside_the_board(method, path):
    """
    Given an account outside the board, signed in
    When it calls any operation on the tasks
    Then it is refused with a 403
    """
    client = Client(headers={"Authorization": f"Bearer {AccessToken.for_user(UserFactory())}"})

    assert getattr(client, method)(path).status_code == 403


# List


def test_open_tasks_come_by_due_date_then_those_done_as_they_were_done(board_client):
    """
    Given an event with open tasks due on 20 and 8 October and one without a
    due date, two tasks done on 30 then 25 September, and a task of another event
    When the board lists the event's tasks
    Then the open ones come first, the one due the soonest first and the one
    without a due date last, then those done in the order they were done
    """
    halloween = EventFactory()
    now = timezone.now()
    TaskFactory(event=halloween, title="Affichettes", due_date=dt.date(2026, 10, 20))
    TaskFactory(event=halloween, title="Arrêté", done_at=now - dt.timedelta(days=10))
    TaskFactory(event=halloween, title="Sans échéance")
    TaskFactory(event=halloween, title="Devis sono", due_date=dt.date(2026, 10, 8))
    TaskFactory(event=halloween, title="Bonbons", done_at=now - dt.timedelta(days=15))
    TaskFactory(title="Lots du loto")

    assert listed_titles(board_client, halloween) == [
        "Devis sono",
        "Affichettes",
        "Sans échéance",
        "Bonbons",
        "Arrêté",
    ]


def test_a_listed_task_holds_its_assignee_due_date_and_when_it_was_done(board_client):
    """
    Given a task done, assigned to Julie and due on 8 October
    When the board lists the event's tasks
    Then the task comes with its event, title, assignee, due date, when it was
    done and who created it
    """
    julie = BoardMemberFactory(first_name="Julie", last_name="Roux")
    task = TaskFactory(
        assignee=julie, due_date=dt.date(2026, 10, 8), done_at=timezone.now(), title="Devis"
    )

    assert board_client.get(TASKS, {"event": task.event_id}).json()["items"] == [
        {
            "id": task.id,
            "event": task.event_id,
            "title": "Devis",
            "assignee": member_json(julie),
            "due_date": "2026-10-08",
            "done_at": iso(task.done_at),
            "created_by": member_json(task.created_by),
        }
    ]


def test_the_tasks_come_by_page(board_client):
    """
    Given an event with three tasks
    When the board lists them by pages of two
    Then the first page holds two tasks, and the count tells there are three
    """
    event = EventFactory()
    TaskFactory.create_batch(3, event=event)

    body = board_client.get(TASKS, {"event": event.id, "page_size": 2}).json()

    assert (len(body["items"]), body["count"]) == (2, 3)


def test_listing_the_tasks_reads_their_people_at_once(board_client, django_assert_max_num_queries):
    """
    Given an event with five tasks, each assigned
    When the board lists the event's tasks
    Then the tasks and their people take a fixed number of queries
    """
    event = EventFactory()
    for task in TaskFactory.create_batch(5, event=event):
        task.assignee = task.created_by
        task.save()

    # Authentication (2), count and page of tasks with their people.
    with django_assert_max_num_queries(4):
        response = board_client.get(TASKS, {"event": event.id})

    assert len(response.json()["items"]) == 5


# Writing


def test_the_general_tasks_are_those_without_an_event(board_client):
    """
    Given two general tasks, the later one due first, and a task of an event
    When a member lists the general tasks
    Then they come by page, the one due the soonest first, without the event's
    """
    later = TaskFactory(event=None, title="Préparer l’AG", due_date=dt.date(2026, 11, 20))
    sooner = TaskFactory(event=None, title="Renouveler l’assurance", due_date=dt.date(2026, 11, 15))
    TaskFactory(title="Valider le devis sono")

    response = board_client.get(f"{TASKS}/general")

    assert response.status_code == 200
    assert response.json()["count"] == 2
    assert [task["title"] for task in response.json()["items"]] == [sooner.title, later.title]
    assert response.json()["items"][0]["event"] is None


def test_the_general_tasks_are_not_taken_for_a_task_id(board_client):
    """
    Given the path of the general tasks, which reads like the path of a task
    When a member lists them
    Then the list answers: the path of a task, which only writes, does not
    take "general" for an id and refuse the reading
    """
    assert board_client.get(f"{TASKS}/general").status_code == 200


def test_a_member_creates_a_task_of_an_event(board_client, board_member):
    """
    Given an event and a member of the board
    When a member creates a task assigned to that member, due on 8 October
    Then the task is recorded open, created by the signed-in member
    """
    event = EventFactory()
    julie = BoardMemberFactory()

    response = send(
        board_client,
        "post",
        TASKS,
        task_payload(event, title=" Devis sono ", assignee=julie.id, due_date="2026-10-08"),
    )

    assert response.status_code == 201
    task = Task.objects.get()
    assert (task.event, task.title, task.assignee, task.due_date, task.done_at) == (
        event,
        "Devis sono",
        julie,
        dt.date(2026, 10, 8),
        None,
    )
    assert task.created_by == board_member
    assert response.json()["id"] == task.id


def test_a_task_created_done_records_when(board_client):
    """
    Given an event
    When a member creates a task already done
    Then the task is recorded done, now
    """
    before = timezone.now()

    send(board_client, "post", TASKS, task_payload(EventFactory(), done=True))

    assert Task.objects.get().done_at >= before


def test_ticking_a_task_records_when_it_was_done(board_client):
    """
    Given an open task
    When a member ticks it done
    Then the task is done, now
    """
    task = TaskFactory()
    before = timezone.now()

    response = send(board_client, "put", task_url(task.id), task_payload(task.event, done=True))

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.done_at >= before
    assert response.json()["done_at"] == iso(task.done_at)


def test_a_task_done_keeps_when_it_was_done(board_client):
    """
    Given a task done on 25 September
    When a member rewrites its title, still done
    Then the task keeps the time it was done
    """
    done_at = timezone.now() - dt.timedelta(days=15)
    task = TaskFactory(done_at=done_at)

    send(
        board_client, "put", task_url(task.id), task_payload(task.event, title="Bonbons", done=True)
    )

    task.refresh_from_db()
    assert (task.title, task.done_at) == ("Bonbons", done_at)


def test_unticking_a_task_opens_it_again(board_client):
    """
    Given a task done
    When a member unticks it
    Then the task is open again
    """
    task = TaskFactory(done_at=timezone.now())

    send(board_client, "put", task_url(task.id), task_payload(task.event, done=False))

    task.refresh_from_db()
    assert task.done_at is None


def test_a_task_is_assigned_to_a_board_member_only(board_client):
    """
    Given an account outside the board
    When a member assigns a task to it
    Then the task is refused with a 422, located under its assignee
    """
    outsider = UserFactory()

    response = send(board_client, "post", TASKS, task_payload(EventFactory(), assignee=outsider.id))

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "assignee"],
            "msg": "Choisissez un membre du bureau.",
        }
    ]


def test_a_former_member_stays_assigned_until_the_assignment_changes(board_client):
    """
    Given a task assigned to a member who has since left the board
    When a member ticks the task, its assignee unchanged
    Then the task is saved, still assigned to the former member
    """
    former = BoardMemberFactory()
    task = TaskFactory(assignee=former)
    former.groups.clear()

    response = send(
        board_client,
        "put",
        task_url(task.id),
        task_payload(task.event, assignee=former.id, done=True),
    )

    assert response.status_code == 200
    task.refresh_from_db()
    assert task.assignee == former


@pytest.mark.parametrize(
    ("change", "location", "message"),
    [
        ({"title": "  "}, ["body", "title"], "Ce champ ne peut pas être vide."),
        ({"event": 987654}, ["body", "event"], "Choisissez un événement existant."),
        ({"due_date": "31/10/2026"}, ["body", "payload", "due_date"], "Saisissez une date valide."),
    ],
    ids=["title", "event", "due date"],
)
def test_a_faulty_task_is_refused_in_french_under_its_field(
    board_client, change, location, message
):
    """
    Given an event
    When a member sends a task without title, on an unknown event, or due on a
    date written the French way
    Then the task is refused with a 422, in French, under the field at fault
    """
    response = send(board_client, "post", TASKS, task_payload(EventFactory()) | change)

    assert response.status_code == 422
    assert [(error["loc"], error["msg"]) for error in response.json()["detail"]] == [
        (location, message)
    ]


def test_a_member_deletes_a_task(board_client):
    """
    Given a task
    When a member deletes it
    Then the task is gone
    """
    task = TaskFactory()

    response = board_client.delete(task_url(task.id))

    assert response.status_code == 204
    assert not Task.objects.exists()


@pytest.mark.parametrize(("method", "payload"), [("put", {"title": "Tâche"}), ("delete", None)])
def test_an_unknown_task_is_not_found(board_client, method, payload):
    """
    Given no task of id 987654
    When a member rewrites or deletes it
    Then the answer is a 404, in French
    """
    body = task_payload(EventFactory()) | payload if payload else None

    response = send(board_client, method, task_url(987654), body)

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}
