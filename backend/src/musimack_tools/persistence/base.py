"""SQLAlchemy declarative base; importing it creates no engine or session."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
