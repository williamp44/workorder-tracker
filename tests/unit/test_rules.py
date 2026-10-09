"""app/rules.py is the functional core: pure decisions over immutable data.

No database, no mocks: a pure function needs neither.
"""

import pytest

from app import rules
from app.models import Status
from tests.spec import EXPECTED_ALLOWED


@pytest.mark.parametrize("src", list(Status), ids=lambda s: s.value)
@pytest.mark.parametrize("dst", list(Status), ids=lambda s: s.value)
def test_can_transition_matches_the_hand_written_spec(src, dst):
    assert rules.can_transition(src, dst) == ((src.value, dst.value) in EXPECTED_ALLOWED)


def test_the_transition_table_cannot_be_rebound_at_run_time():
    with pytest.raises(TypeError):
        rules.ALLOWED_TRANSITIONS[Status.done] = frozenset({Status.open})  # type: ignore[index]


def test_a_transition_set_cannot_be_extended_at_run_time():
    with pytest.raises(AttributeError):
        rules.ALLOWED_TRANSITIONS[Status.open].add(Status.done)  # type: ignore[attr-defined]
