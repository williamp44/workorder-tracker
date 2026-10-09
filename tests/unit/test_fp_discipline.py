"""tools/check_fp.py: the functional-programming rules, checked not merely written.

Each rule is shown firing on the shape it exists for and staying quiet on the
nearest correct shape, then the whole repo must be clean.
"""

import pytest

from tools.check_fp import check_source, check_tree


def rules_fired(src: str, path: str = "app/x.py", pure: bool = False) -> list[str]:
    return [f.rule for f in check_source(src, path, pure=pure)]


@pytest.mark.parametrize("src", [
    "X = {}", "X = []", "X = set()", "X = dict(a=1)", "X: dict[str, int] = {'a': 1}",
    "X = [y for y in range(3)]", "X = {y: y for y in range(3)}",
])
def test_mutable_constant_fires(src):
    assert rules_fired(src) == ["mutable-constant"]


@pytest.mark.parametrize("src", [
    "X = ()", "X = frozenset({1})", "X = MappingProxyType({'a': 1})", "X = 3", "X = 'a'",
    "x = []",  # not a constant: lower case
    "def f():\n    X = []\n    return X",  # local, not module level
])
def test_mutable_constant_is_quiet_on_immutable_or_local_values(src):
    assert rules_fired(src) == []


@pytest.mark.parametrize("src", [
    "def f(xs):\n    xs.append(1)",
    "def f(d):\n    d['k'] = 1",
    "def f(d):\n    d['a']['b'] = 1",
    "def f(o):\n    o.attr = 1",
    "def f(d):\n    del d['k']",
    "def f(xs):\n    xs[0] += 1",
])
def test_mutated_argument_fires_in_a_pure_module(src):
    assert rules_fired(src, pure=True) == ["mutated-argument"]


@pytest.mark.parametrize("src", [
    "def f(xs):\n    ys = list(xs)\n    ys.append(1)\n    return ys",
    "def f(x):\n    x = x + 1\n    return x",
])
def test_mutated_argument_is_quiet_on_a_copy_or_a_rebinding(src):
    assert rules_fired(src, pure=True) == []


def test_mutated_argument_does_not_apply_to_the_imperative_shell():
    # services.py takes a session and mutates it; that is its job.
    assert rules_fired("def f(session, x):\n    session.add(x)") == []


@pytest.mark.parametrize("src", [
    "import sqlalchemy", "from fastapi import Depends", "import subprocess", "import os",
    "async def f():\n    pass", "def f():\n    global X",
])
def test_pure_module_does_no_io(src):
    assert rules_fired(src, pure=True) == ["impure-core"]


@pytest.mark.parametrize("src", [
    "from unittest import mock", "import unittest.mock", "from unittest.mock import patch",
    "def test_a(monkeypatch):\n    pass", "def test_a(mocker):\n    pass",
])
def test_mock_in_a_unit_test_fires(src):
    assert rules_fired(src, path="tests/unit/test_x.py") == ["mock-in-unit-test"]


def test_mocks_are_allowed_in_integration_tests():
    assert rules_fired("def test_a(monkeypatch):\n    pass", path="tests/integration/test_x.py") == []


def test_the_repo_follows_the_rules():
    findings = check_tree()
    assert findings == [], "\n".join(map(str, findings))
