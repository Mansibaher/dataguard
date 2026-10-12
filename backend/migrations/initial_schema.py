from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    String,
    Integer,
    Float,
    JSON,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    LargeBinary,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password: Mapped[str] = mapped_column(String(300))


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(300))
    provenance: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    original: Mapped[bytes] = mapped_column(LargeBinary)
    columns: Mapped[list] = mapped_column(JSON)
    row_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class InputRow(Base):
    __tablename__ = "input_rows"
    __table_args__ = (UniqueConstraint("dataset_id", "number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    values: Mapped[dict] = mapped_column(JSON)


class Configuration(Base):
    __tablename__ = "configurations"
    __table_args__ = (UniqueConstraint("dataset_id", "version"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    rules: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    configuration_id: Mapped[str] = mapped_column(ForeignKey("configurations.id"))
    kind: Mapped[str] = mapped_column(String(20), default="initial")
    state: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    total: Mapped[int] = mapped_column(Integer)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Quarantine(Base):
    __tablename__ = "quarantine"
    __table_args__ = (UniqueConstraint("run_id", "row_number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    configuration_id: Mapped[str] = mapped_column(ForeignKey("configurations.id"))
    row_number: Mapped[int] = mapped_column(Integer)
    original: Mapped[dict] = mapped_column(JSON)
    failures: Mapped[list] = mapped_column(JSON)
    corrected: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ReplayItem(Base):
    __tablename__ = "replay_items"
    __table_args__ = (
        UniqueConstraint("run_id", "number"),
        UniqueConstraint("run_id", "quarantine_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    quarantine_id: Mapped[str] = mapped_column(ForeignKey("quarantine.id"))
    number: Mapped[int] = mapped_column(Integer)
    values: Mapped[dict] = mapped_column(JSON)
    outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)
    failures: Mapped[list] = mapped_column(JSON, default=list)


class Accepted(Base):
    __tablename__ = "accepted"
    __table_args__ = (
        UniqueConstraint("dataset_id", "business_key"),
        UniqueConstraint("run_id", "row_number"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    business_key: Mapped[str] = mapped_column(String(64))
    values: Mapped[dict] = mapped_column(JSON)
    quarantine_id: Mapped[str | None] = mapped_column(
        ForeignKey("quarantine.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id"), nullable=True, index=True
    )
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


Index("ix_input_order", InputRow.dataset_id, InputRow.number)
Index("ix_replay_order", ReplayItem.run_id, ReplayItem.number)

metadata = Base.metadata
