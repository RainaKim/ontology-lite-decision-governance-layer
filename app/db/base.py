"""
app/db/base.py — Declarative base shared by all ORM models.

Import this module (and all models that subclass Base) before running
Alembic autogenerate so the metadata is fully populated.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Single declarative base for all ORM models."""
    pass
