from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models import CellType, ExecStatus, LLMProvider


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    llm_provider: LLMProvider | None = None
    llm_model: str | None = None
    llm_temperature: int | None = Field(default=None, ge=0, le=2)
    api_base_url: str | None = None
    api_key: str | None = None
    target_database_url: str | None = None
    allow_writes: bool | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    llm_provider: LLMProvider
    llm_model: str
    llm_temperature: int
    api_base_url: str | None
    allow_writes: bool
    target_db_configured: bool = False
    created_at: datetime
    updated_at: datetime


class ChatMessageCreate(BaseModel):
    message: str


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SQLGenerateIn(BaseModel):
    question: str


class SQLGenerateOut(BaseModel):
    sql: str
    explanation: str = ""
    safety_notes: str = "Read-only by default."


class SQLRunIn(BaseModel):
    sql: str


class SQLRunOut(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int


class SavedQueryCreate(BaseModel):
    name: str
    sql: str


class SavedQueryOut(BaseModel):
    id: uuid.UUID
    name: str
    sql: str
    created_at: datetime


class FileOut(BaseModel):
    id: uuid.UUID
    name: str
    size_bytes: int
    mime_type: str | None
    created_at: datetime


class FilePreviewOut(BaseModel):
    columns: list[str]
    rows: list[list[Any]]


class FileProfileOut(BaseModel):
    profile: dict[str, Any]


class FileAnalysisSuggestion(BaseModel):
    title: str
    description: str = ""
    cell_type: Literal["python", "markdown"] = "python"
    code: str


class FileAnalyzeOut(BaseModel):
    suggestions: list[FileAnalysisSuggestion]


class ProjectContextOut(BaseModel):
    schema_summary: str
    files: list[FileOut]
    recent_cells: list[WorkspaceCellOut]


class DBTestOut(BaseModel):
    ok: bool
    message: str = ""
    schema_summary: str = ""


class WorkspaceCellCreate(BaseModel):
    type: CellType
    source: str = ""
    position: int | None = None


class WorkspaceCellPatch(BaseModel):
    source: str | None = None
    position: int | None = None


class WorkspaceCellOut(BaseModel):
    id: uuid.UUID
    type: CellType
    position: int
    source: str
    status: ExecStatus
    stdout: str
    stderr: str
    result: dict[str, Any] | None
    executed_at: datetime | None
    runtime_ms: int | None


class ExecuteOut(BaseModel):
    stdout: str = ""
    stderr: str = ""
    result: dict[str, Any] | None = None

