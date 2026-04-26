"""Importing this package registers all tasks via side effect."""
from . import definitions  # noqa: F401 — registers tasks
from .registry import Task, all_tasks, get, register

__all__ = ["Task", "all_tasks", "get", "register"]
