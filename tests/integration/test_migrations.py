"""Migrations must build exactly the schema the models describe, and must
round-trip (upgrade -> downgrade -> upgrade) cleanly."""

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def _config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["url_set_by_caller"] = True
    cfg.attributes["configure_logger"] = False
    return cfg


def _url(tmp_path) -> str:
    return os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'm.db'}"


def test_migrations_match_models_and_round_trip(tmp_path):
    cfg = _config(_url(tmp_path))
    command.upgrade(cfg, "head")
    try:
        # Raises if autogenerate would emit anything: models and migrations agree.
        command.check(cfg)
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")
    finally:
        command.downgrade(cfg, "base")
