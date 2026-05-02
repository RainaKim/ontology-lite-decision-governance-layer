"""
Alembic env.py — wires DATABASE_URL + ORM metadata for migrations.

Usage:
  alembic upgrade head       # apply all migrations
  alembic downgrade -1       # roll back one migration
  alembic revision --autogenerate -m "description"  # generate new migration
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make sure app/ is importable when running alembic from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import Base — all models that subclass it must be imported here so that
# autogenerate can detect their tables.
from app.db.base import Base  # noqa: E402
import app.models.user  # noqa: E402, F401 — registers User with Base.metadata
import app.models.company  # noqa: E402, F401 — registers Company with Base.metadata
import app.models.decision  # noqa: E402, F401 — registers Decision with Base.metadata

config = context.config

# Override sqlalchemy.url with DATABASE_URL env var (takes precedence over alembic.ini).
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./dev.db")
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# ---------------------------------------------------------------------------
# Offline migrations (no live DB connection)
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations (live DB connection)
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
