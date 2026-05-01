"""Naming convention enforces stable, deterministic constraint names."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from iguanatrader.persistence.base import Base


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
    pk = next(iter(_ParentTbl.__table__.primary_key))
    assert _ParentTbl.__table__.primary_key.name == "pk__test_parent"
    assert pk.name == "id"


def test_fk_name_pattern() -> None:
    fks = list(_ChildTbl.__table__.foreign_keys)
    assert len(fks) == 1
    assert fks[0].constraint.name == "fk__test_child_parent_id__test_parent"


def test_uq_name_pattern_single_column() -> None:
    uqs = [c for c in _ParentTbl.__table__.constraints if isinstance(c, UniqueConstraint)]
    assert len(uqs) == 1
    assert uqs[0].name == "uq__test_parent_name"


def test_uq_name_pattern_multi_column_first_column() -> None:
    uqs = [c for c in _ChildTbl.__table__.constraints if isinstance(c, UniqueConstraint)]
    assert len(uqs) == 1
    assert uqs[0].name == "uq__test_child_parent_id"


def test_ix_name_pattern() -> None:
    indexes = list(_ChildTbl.__table__.indexes)
    assert len(indexes) == 1
    assert indexes[0].name == "ix__test_child_label"
