"""SQLAlchemy declarative base + naming convention for autogenerate stability."""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata: MetaData = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Project-wide declarative base. All ORM models inherit from this.

    Class attributes (read by global listeners — see :mod:`persistence.tenant_listener`
    and :mod:`persistence.append_only_listener`):

    - ``__tenant_scoped__: bool = True`` — set ``False`` to opt out of tenant filter
      (e.g. cross-tenant catalogues like ``research_sources`` per data-model §3.1).
    - ``__tablename_is_append_only__: bool = False`` — set ``True`` to refuse
      UPDATE/DELETE at flush time (per spec scenario "UPDATE on append-only row
      raises before reaching the driver").
    """

    metadata = metadata

    __tenant_scoped__: bool = True
    __tablename_is_append_only__: bool = False
