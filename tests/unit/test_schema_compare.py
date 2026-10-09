"""`alembic check` compares server defaults (a migration whose default drifted
from the model used to pass). Databases spell "now" differently when they
reflect it, so equal defaults must compare equal, and different ones must not.
Found by: CI on MariaDB, which reflects now() as current_timestamp().
"""

import pytest

from app.schema_compare import same_server_default


@pytest.mark.parametrize("reflected,model", [
    ("current_timestamp()", "now()"),
    ("CURRENT_TIMESTAMP", "now()"),
    ("(CURRENT_TIMESTAMP)", "now()"),
    ("now()", "now()"),
    ("'abc'", "'abc'"),
])
def test_equal_defaults_compare_equal(reflected, model):
    assert same_server_default(reflected, model) is True


@pytest.mark.parametrize("reflected,model", [
    ("'2000-01-01'", "now()"),
    ("'2000-01-01 00:00:00'", "now()"),
    ("current_timestamp()", "'2000-01-01'"),
    (None, "now()"),
    ("now()", None),
])
def test_different_defaults_do_not(reflected, model):
    assert same_server_default(reflected, model) is False
