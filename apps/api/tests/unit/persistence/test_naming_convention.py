"""Naming convention enforces stable, deterministic constraint names."""

from __future__ import annotations

from iguanatrader.persistence.base import Base
from sqlalchemy import Column, ForeignKey, ForeignKeyConstraint, Index, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class _ParentTbl(Base):
    __tablename__ = "_test_parent"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class _ChildTbl(Base):
    __tablename__ = "_test_child"
    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("_test_parent.id"))
    label: Mapped[str]

    __table_args__ = (
        UniqueConstraint("parent_id", "label"),
        Index(None, "label"),
    )


def test_pk_name_pattern() -> None:
    table: Table = _ParentTbl.__table__
    pk_columns = list(table.primary_key.columns)
    pk: Column[int] = pk_columns[0]
    assert table.primary_key.name == "pk__test_parent"
    assert pk.name == "id"


def test_fk_name_pattern() -> None:
    table: Table = _ChildTbl.__table__
    fks = list(table.foreign_keys)
    assert len(fks) == 1
    constraint: ForeignKeyConstraint | None = fks[0].constraint
    assert constraint is not None
    assert constraint.name == "fk__test_child_parent_id__test_parent"


def test_uq_name_pattern_single_column() -> None:
    table: Table = _ParentTbl.__table__
    uqs = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert len(uqs) == 1
    assert uqs[0].name == "uq__test_parent_name"


def test_uq_name_pattern_multi_column_first_column() -> None:
    table: Table = _ChildTbl.__table__
    uqs = [c for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert len(uqs) == 1
    assert uqs[0].name == "uq__test_child_parent_id"


def test_ix_name_pattern() -> None:
    table: Table = _ChildTbl.__table__
    indexes = list(table.indexes)
    assert len(indexes) == 1
    assert indexes[0].name == "ix__test_child_label"
