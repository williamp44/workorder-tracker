"""Suites run on a copied tree must import the copy, never the working copy.

Found by: check_red in CI. With the project installed editable (pip install
-e), setuptools' finder served app.rules from the working copy to a base
tree that did not have it, so new tests "passed before the change". Only
fails under an editable install, which is how CI installs.
"""

import subprocess
from pathlib import Path

from tools.isolation import pytest_command


def test_a_copied_tree_cannot_import_modules_it_does_not_contain(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "__init__.py").write_text("")
    probe = tmp_path / "tests" / "test_probe.py"
    probe.parent.mkdir()
    probe.write_text(
        "import importlib, pytest\n"
        "def test_rules_is_absent():\n"
        "    with pytest.raises(ModuleNotFoundError):\n"
        "        importlib.import_module('app.rules')\n"
    )
    r = subprocess.run(pytest_command("-q", "-p", "no:cacheprovider", "tests"),
                       cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
