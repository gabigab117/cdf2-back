"""The board's tasks, and how far they have gone.

Open tasks come first, the one due the soonest first, those without a due date
last; then the tasks done, in the order they were done.
"""

from django.db.models import Count, F, Q, QuerySet
from django.utils import timezone

from accounts.models import User
from events.models import Event
from tasks.models import Task
from tasks.schemas import TaskIn


def ordered(tasks: QuerySet[Task]) -> QuerySet[Task]:
    """Tasks in the board's order: open first by due date, then done as they were done."""
    return tasks.order_by(
        F("done_at").asc(nulls_first=True), F("due_date").asc(nulls_last=True), "pk"
    )


def event_tasks(event_id: int) -> QuerySet[Task]:
    """The tasks of an event, in the board's order, with their people."""
    tasks = Task.objects.filter(event_id=event_id).select_related("assignee", "created_by")
    return ordered(tasks)


def task_counts(event: Event) -> tuple[int, int]:
    """How many tasks of an event are done, out of how many."""
    counts = event.tasks.aggregate(
        done=Count("pk", filter=Q(done_at__isnull=False)), total=Count("pk")
    )
    return counts["done"], counts["total"]


def next_tasks(event: Event, count: int) -> list[Task]:
    """The open tasks of an event due the soonest."""
    return list(event_tasks(event.pk).filter(done_at__isnull=True)[:count])


def recently_done_tasks(event: Event, count: int) -> list[Task]:
    """The tasks of an event done last, in the order they were done."""
    done = event_tasks(event.pk).filter(done_at__isnull=False).order_by("-done_at", "-pk")
    return list(reversed(done[:count]))


def create_task(data: TaskIn, created_by: User) -> Task:
    """Record a new task of a member."""
    return _save(Task(created_by=created_by), data)


def update_task(task: Task, data: TaskIn) -> Task:
    """Rewrite a task whole, done or not."""
    return _save(task, data)


def delete_task(task: Task) -> None:
    task.delete()


def _save(task: Task, data: TaskIn) -> Task:
    # Only an assignee being chosen must be a board member: whoever has left the
    # board since stays assigned to their tasks.
    assignee_unchanged = task.pk is not None and task.assignee_id == data.assignee
    task.event_id = data.event
    task.title = data.title
    task.assignee_id = data.assignee
    task.due_date = data.due_date
    # A task done keeps the time it was done; one undone forgets it.
    if not data.done:
        task.done_at = None
    elif task.done_at is None:
        task.done_at = timezone.now()
    task.full_clean(exclude={"assignee"} if assignee_unchanged else set())
    task.save()
    return task
