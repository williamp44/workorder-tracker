"""Run pytest in a subprocess that cannot see the working copy.

check_red and the mutation check run the suite on copied trees (the base
branch, a mutant). With the project installed editable (`pip install -e`),
setuptools adds an import finder that serves the package from the working
copy, so a copied tree missing a module silently imports the working copy's
version. check_red then reported new tests as passing "before the change".

The subprocess drops those finders before pytest starts, so a copied tree
imports only itself and whatever is genuinely installed.
"""

import sys

_BOOTSTRAP = (
    "import sys\n"
    "sys.meta_path[:] = [f for f in sys.meta_path\n"
    "                    if not getattr(f, '__module__', '').startswith('__editable__')]\n"
    "import pytest\n"
    "sys.exit(pytest.main(sys.argv[1:]))\n"
)


def pytest_command(*args: str) -> list[str]:
    return [sys.executable, "-c", _BOOTSTRAP, *args]
