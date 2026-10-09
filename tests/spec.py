"""The transition spec: the oracle, written out by hand.

Independent of app.rules.ALLOWED_TRANSITIONS on purpose. Deriving test cases
from the table under test would make them a tautology: a wrong table would
generate matching wrong tests and still pass.
"""

EXPECTED_ALLOWED = frozenset({
    ("open", "in_progress"),
    ("open", "cancelled"),
    ("in_progress", "done"),
    ("in_progress", "open"),
    ("in_progress", "cancelled"),
})
