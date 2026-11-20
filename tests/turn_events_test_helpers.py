"""Shared turn-event start wait recorder."""

import threading
import time


class _AckCountedFrom(threading.Event):
    """The writer's acknowledgement, whose wait in start() begins only once `ready` is set: the
    start bound then passes with the writer provably inside the blocked step. Getting there has
    its own generous limit; `bound_began` is when the real wait began, so a test that times
    the caller measures only the bound, never the writer's way to its start position."""

    def __init__(self, ready: threading.Event) -> None:
        super().__init__()
        self._ready = ready
        self.bound_began: float | None = None
        self.timeouts: list[float | None] = []

    def wait(self, timeout: float | None = None) -> bool:
        self.timeouts.append(timeout)
        assert self._ready.wait(30)
        self.bound_began = time.monotonic()
        return super().wait(timeout)
