from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LLMProvider(str, enum.Enum):
    ollama = "ollama"
    api = "api"


class CellType(str, enum.Enum):
    markdown = "markdown"
    python = "python"
    sql = "sql"


class ExecStatus(str, enum.Enum):
    idle = "idle"
    running = "running"
    success = "success"
    error = "error"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    llm_provider: Mapped[LLMProvider] = mapped_column(Enum(LLMProvider), nullable=False, default=LLMProvider.ollama)
    llm_model: Mapped[str] = mapped_column(String(200), nullable=False, default="llama3")
    llm_temperature: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    api_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    allow_writes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    chat_messages: Mapped[list[ChatMessage]] = relationship(back_populates="project", cascade="all, delete-orphan")
    files: Mapped[list[ProjectFile]] = relationship(back_populates="project", cascade="all, delete-orphan")
    cells: Mapped[list[WorkspaceCell]] = relationship(back_populates="project", cascade="all, delete-orphan")
    saved_queries: Mapped[list[SavedQuery]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))

    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user|assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="chat_messages")


class ProjectFile(Base):
    __tablename__ = "project_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String(400), nullable=False)
    path: Mapped[str] = mapped_column(String(800), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(200), nullable=True)

    profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    preview: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="files")


class WorkspaceCell(Base):
    __tablename__ = "workspace_cells"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))

    type: Mapped[CellType] = mapped_column(Enum(CellType), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    source: Mapped[str] = mapped_column(Text, nullable=False, default="")

    status: Mapped[ExecStatus] = mapped_column(Enum(ExecStatus), nullable=False, default=ExecStatus.idle)
    stdout: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runtime_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    project: Mapped[Project] = relationship(back_populates="cells")


class SavedQuery(Base):
    __tablename__ = "saved_queries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="saved_queries")
