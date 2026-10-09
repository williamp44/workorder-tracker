"""The mutation check is itself a check, so it gets tested like code.

These tests cover the pure parts: applying a mutant and judging the run.
The end-to-end run (copy the tree, break it, run pytest) is
tools/mutation_check.py itself, run in CI.
"""

from pathlib import Path

import pytest

from tools.mutation_check import MUTANTS, MutantDoesNotApply, apply, verdict

ROOT = Path(__file__).resolve().parent.parent


def test_apply_replaces_the_single_occurrence():
    assert apply("a == b and c", "a == b", "True") == "True and c"


def test_apply_refuses_a_pattern_that_is_not_there():
    # Otherwise the "mutant" is the unchanged code, the suite passes, and the
    # report blames the tests for a mutation that never happened.
    with pytest.raises(MutantDoesNotApply):
        apply("a == b", "x == y", "True")


def test_apply_refuses_an_ambiguous_pattern():
    with pytest.raises(MutantDoesNotApply):
        apply("a == b; a == b", "a == b", "True")


@pytest.mark.parametrize("mutant", MUTANTS, ids=lambda m: m.name)
def test_every_mutant_still_applies_to_the_current_source(mutant):
    # If app code is edited, a mutant's pattern can silently stop matching.
    source = (ROOT / mutant.path).read_text()
    assert apply(source, mutant.old, mutant.new) != source


def test_verdict_passes_only_when_control_passes_and_every_mutant_is_killed():
    assert verdict(control_exit=0, mutant_exits={"m1": 1, "m2": 1}) == []


def test_verdict_reports_a_surviving_mutant():
    assert verdict(control_exit=0, mutant_exits={"m1": 1, "m2": 0}) == [
        "m2 survived: the suite passed with the bug in place"
    ]


def test_verdict_fails_when_the_unmutated_control_fails():
    # A red control makes every mutant look killed.
    problems = verdict(control_exit=1, mutant_exits={"m1": 1})
    assert problems == ["control failed: the suite is red without any mutation"]


def test_verdict_treats_a_pytest_usage_error_as_not_killed():
    # Exit 1 = tests failed. Exit 2-5 = pytest could not run the suite, which
    # proves nothing about the tests catching the bug.
    assert verdict(control_exit=0, mutant_exits={"m1": 4}) == [
        "m1 inconclusive: pytest exited 4, not 1"
    ]


def test_verdict_fails_when_an_equivalent_mutant_is_killed():
    # An equivalent mutant changes nothing a test can observe. If the suite
    # fails on it, something other than app behaviour is failing the suite,
    # and every other "kill" in the run is suspect.
    problems = verdict(control_exit=0, mutant_exits={"canary": 1}, equivalent={"canary"})
    assert problems == ["canary was killed but changes no behaviour: the kills are not trustworthy"]


def test_verdict_accepts_a_surviving_equivalent_mutant():
    assert verdict(control_exit=0, mutant_exits={"canary": 0, "m1": 1}, equivalent={"canary"}) == []


def test_the_run_includes_an_equivalent_mutant():
    assert any(m.equivalent for m in MUTANTS)
