from django.shortcuts import get_object_or_404
from ninja import Router, Status
from ninja.pagination import paginate

from core.schemas import ErrorOut, ValidationErrorOut
from tasks.models import Task
from tasks.schemas import TaskIn, TaskOut
from tasks.services.tasks import create_task, delete_task, event_tasks, update_task

router = Router(tags=["tasks"])


@router.get(
    "/tasks",
    response={200: list[TaskOut], 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="List the tasks of an event",
)
@paginate
def list_tasks(request, event: int):
    """The tasks of an event, by page: open first by due date, then those done."""
    return event_tasks(event)


@router.post(
    "/tasks",
    response={
        201: TaskOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Create a task",
)
def create(request, payload: TaskIn):
    """Record a task of the signed-in member."""
    return Status(201, create_task(payload, request.auth))


@router.put(
    "/tasks/{task_id}",
    response={
        200: TaskOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Update a task",
)
def update(request, task_id: int, payload: TaskIn):
    """Rewrite a task whole: ticking it done records when."""
    return update_task(get_object_or_404(Task, pk=task_id), payload)


@router.delete(
    "/tasks/{task_id}",
    response={204: None, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ValidationErrorOut},
    summary="Delete a task",
)
def delete(request, task_id: int):
    delete_task(get_object_or_404(Task, pk=task_id))
    return Status(204, None)
