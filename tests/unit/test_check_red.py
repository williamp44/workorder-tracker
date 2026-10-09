"""tools/check_red.py: every new test must fail against the code before the change.

A new test that already passes on the base branch tests nothing the change
did. Either it was written after the code, or it cannot fail. These cover
the pure verdict; CI runs the tool itself on every pull request.
"""

from tools.check_red import key, verdict


def test_key_ignores_the_directory_so_a_moved_test_is_not_new():
    assert key("tests.unit.test_rules", "test_a") == key("tests.test_rules", "test_a")


def test_key_keeps_parametrized_cases_distinct():
    assert key("tests.unit.test_rules", "test_a[x]") != key("tests.unit.test_rules", "test_a[y]")


def test_a_new_test_that_was_red_on_base_passes_the_gate():
    assert verdict(new={"m::t"}, base={"m::t": "RED"}, controls=frozenset()) == []


def test_a_new_test_the_base_could_not_even_collect_counts_as_red():
    assert verdict(new={"m::t"}, base={}, controls=frozenset()) == []


def test_a_new_test_that_was_already_green_on_base_fails_the_gate():
    assert verdict(new={"m::t"}, base={"m::t": "GREEN"}, controls=frozenset()) == [
        "m::t passed before the change: it was not RED first, or it cannot fail"
    ]


def test_a_declared_control_may_be_green_on_base():
    # A control pins behaviour that must KEEP working, so green on base is the point.
    assert verdict(new={"m::t"}, base={"m::t": "GREEN"}, controls=frozenset({"m::t"})) == []


def test_a_skipped_test_is_not_evidence_of_red():
    assert verdict(new={"m::t"}, base={"m::t": "SKIP"}, controls=frozenset()) == [
        "m::t was skipped on base, so it was never seen failing"
    ]
