"""Task base class + registration helpers."""
from __future__ import annotations

from pydantic import BaseModel, Field


class Task(BaseModel):
    task_id: str
    description: str
    starting_url: str
    success_check_name: str
    timeout_steps: int = Field(default=30, ge=1)


_REGISTRY: dict[str, Task] = {}


def register(task: Task) -> Task:
    if task.task_id in _REGISTRY:
        raise ValueError(f"Task {task.task_id!r} already registered")
    _REGISTRY[task.task_id] = task
    return task


def get(task_id: str) -> Task:
    if task_id not in _REGISTRY:
        raise KeyError(f"Unknown task {task_id!r}. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[task_id]


def all_tasks() -> list[Task]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]
