"""The functional core: what may happen, decided without touching anything.

Pure functions over immutable data. No database, no I/O, no async, so the
rules are tested directly, with no fixtures and no mocks. app/services.py is
the imperative shell that reads, asks these rules, and writes.
tools/check_fp.py enforces the boundary.
"""

from collections.abc import Mapping
from types import MappingProxyType

from app.models import Status

ALLOWED_TRANSITIONS: Mapping[Status, frozenset[Status]] = MappingProxyType({
    Status.open: frozenset({Status.in_progress, Status.cancelled}),
    Status.in_progress: frozenset({Status.done, Status.open, Status.cancelled}),
    Status.done: frozenset(),
    Status.cancelled: frozenset(),
})


def can_transition(current: Status, new: Status) -> bool:
    return new in ALLOWED_TRANSITIONS[current]
