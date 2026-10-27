"""Per-run events, cooperative cancellation and usage. Never redirects stdout."""
from contextvars import ContextVar
from dataclasses import dataclass, field
import threading
import time


class RunStopped(Exception):
    pass


@dataclass
class RunContext:
    emit: object = lambda event: None
    cancelled: threading.Event = field(default_factory=threading.Event)
    deadline: float = field(default_factory=lambda: time.monotonic() + 240)
    metrics: dict = field(default_factory=lambda: {
        "llm_requests": 0, "search_requests": 0, "search_credits": 0,
        "input_tokens": 0, "output_tokens": 0, "stage_seconds": {},
    })

    def check(self):
        if self.cancelled.is_set() or time.monotonic() >= self.deadline:
            raise RunStopped("Run cancelled or time limit reached.")


current_run: ContextVar[RunContext | None] = ContextVar("current_run", default=None)


def check_run():
    context = current_run.get()
    if context:
        context.check()


def emit(event):
    check_run()
    context = current_run.get()
    if context:
        context.emit(event)


def count_usage(**values):
    context = current_run.get()
    if context:
        for key, value in values.items():
            context.metrics[key] += value or 0
