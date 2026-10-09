"""Server-default comparison for `alembic check`.

Databases reflect "the current time" in their own spelling: MariaDB says
current_timestamp(), SQLite says CURRENT_TIMESTAMP, the model says now().
Those are one default. Anything else is compared as written.
"""

NOW = frozenset({"now()", "current_timestamp()", "current_timestamp"})


def _normal(sql: str | None) -> str | None:
    if sql is None:
        return None
    text = sql.strip().lower()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return "now()" if text in NOW else text


def same_server_default(reflected: str | None, model: str | None) -> bool:
    return _normal(reflected) == _normal(model)
