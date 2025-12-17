from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import engine, get_db, get_target_db
from app.executor_client import execute_python, preview_file, profile_file
from app.llm import generate_sql
from app.models import Base, CellType, ChatMessage, ExecStatus, Project, ProjectFile, SavedQuery, WorkspaceCell
from app.schema_introspection import get_schema_summary
from app.schemas import (
    ChatMessageCreate,
    ChatMessageOut,
    ExecuteOut,
    FileOut,
    FilePreviewOut,
    FileProfileOut,
    ProjectCreate,
    ProjectOut,
    ProjectPatch,
    SavedQueryCreate,
    SavedQueryOut,
    SQLGenerateIn,
    SQLGenerateOut,
    SQLRunIn,
    SQLRunOut,
    WorkspaceCellCreate,
    WorkspaceCellOut,
    WorkspaceCellPatch,
)
from app.secrets import encrypt_str
from app.settings import settings
from app.sql_safety import assert_read_only

app = FastAPI(title="Unified Data App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
)

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data/projects"))


@app.on_event("startup")
async def _startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _project_dir(project_id: uuid.UUID) -> Path:
    return DATA_ROOT / str(project_id)


async def _run_cell(project: Project, cell: WorkspaceCell, *, db: AsyncSession, tdb: AsyncSession) -> ExecuteOut:
    started = datetime.utcnow()
    cell.status = ExecStatus.running
    cell.stdout = ""
    cell.stderr = ""
    cell.result = None
    await db.commit()

    try:
        if cell.type == CellType.python:
            out = await execute_python(cell.source)
            cell.stdout = out.get("stdout", "")
            cell.stderr = out.get("stderr", "")
            cell.result = out.get("result")

        elif cell.type == CellType.sql:
            if not project.allow_writes:
                assert_read_only(cell.source)
            res = await tdb.execute(text(cell.source))
            rows = res.fetchmany(500)
            cols = list(res.keys())
            cell.result = {"type": "table", "columns": cols, "rows": [list(r) for r in rows]}

        else:
            cell.result = {"type": "markdown", "rendered": cell.source}

        cell.status = ExecStatus.success

    except Exception as e:  # noqa: BLE001
        cell.status = ExecStatus.error
        cell.stderr = str(e)

    finished = datetime.utcnow()
    cell.executed_at = finished
    cell.runtime_ms = int((finished - started).total_seconds() * 1000)
    await db.commit()
    await db.refresh(cell)

    return ExecuteOut(stdout=cell.stdout, stderr=cell.stderr, result=cell.result)


# ---------------- Projects ----------------


@app.post("/projects", response_model=ProjectOut)
async def create_project(payload: ProjectCreate, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    p = Project(name=payload.name)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    _project_dir(p.id).mkdir(parents=True, exist_ok=True)
    (_project_dir(p.id) / "uploads").mkdir(parents=True, exist_ok=True)
    return ProjectOut.model_validate(p, from_attributes=True)


@app.get("/projects", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)) -> list[ProjectOut]:
    rows = (await db.execute(select(Project).order_by(Project.created_at.desc()))).scalars().all()
    return [ProjectOut.model_validate(p, from_attributes=True) for p in rows]


@app.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return ProjectOut.model_validate(p, from_attributes=True)


@app.patch("/projects/{project_id}", response_model=ProjectOut)
async def patch_project(project_id: uuid.UUID, payload: ProjectPatch, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")

    data = payload.model_dump(exclude_unset=True)
    api_key = data.pop("api_key", None)
    for k, v in data.items():
        setattr(p, k, v)

    if api_key is not None:
        p.api_key_encrypted = encrypt_str(api_key) if api_key else None

    p.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(p)
    return ProjectOut.model_validate(p, from_attributes=True)


@app.delete("/projects/{project_id}")
async def delete_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    p = await db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()
    return {"status": "deleted"}


# ---------------- Chat ----------------


@app.get("/projects/{project_id}/chat/history", response_model=list[ChatMessageOut])
async def chat_history(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[ChatMessageOut]:
    rows = (
        await db.execute(
            select(ChatMessage).where(ChatMessage.project_id == project_id).order_by(ChatMessage.created_at.asc())
        )
    ).scalars().all()
    return [ChatMessageOut.model_validate(m, from_attributes=True) for m in rows]


@app.post("/projects/{project_id}/chat", response_model=ChatMessageOut)
async def chat(project_id: uuid.UUID, payload: ChatMessageCreate, db: AsyncSession = Depends(get_db), tdb: AsyncSession = Depends(get_target_db)) -> ChatMessageOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    user_msg = ChatMessage(project_id=project_id, role="user", content=payload.message, meta={})
    db.add(user_msg)
    await db.commit()

    # Minimal Julius-like behavior: try NL→SQL and run if it looks like a data request.
    schema = await get_schema_summary(tdb)
    assistant_text = ""
    meta: dict[str, Any] = {}
    try:
        sql = await generate_sql(project, question=payload.message, schema_summary=schema)
        if not project.allow_writes:
            assert_read_only(sql)
        res = await tdb.execute(text(sql))
        rows = res.fetchmany(10)
        cols = list(res.keys())
        assistant_text = (
            "Here’s a SQL query you can run:\n\n"
            f"{sql}\n\n"
            "Preview (first 10 rows):\n"
            f"Columns: {cols}\n"
            f"Rows: {rows}"
        )
        meta = {
            "actions": [
                {"type": "insert_sql", "sql": sql},
                {"type": "create_sql_cell", "sql": sql},
            ],
            "citations": [
                {"type": "postgres_schema", "summary": schema[:2000]},
            ],
        }
    except Exception as e:  # noqa: BLE001
        assistant_text = f"I couldn’t generate/run SQL automatically: {e}. You can still use the SQL page."
        meta = {"citations": [{"type": "postgres_schema", "summary": schema[:2000]}]}

    assistant_msg = ChatMessage(project_id=project_id, role="assistant", content=assistant_text, meta=meta)
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)
    return ChatMessageOut.model_validate(assistant_msg, from_attributes=True)


# ---------------- SQL ----------------


@app.post("/projects/{project_id}/sql/generate", response_model=SQLGenerateOut)
async def sql_generate(project_id: uuid.UUID, payload: SQLGenerateIn, db: AsyncSession = Depends(get_db), tdb: AsyncSession = Depends(get_target_db)) -> SQLGenerateOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    schema = await get_schema_summary(tdb)
    sql = await generate_sql(project, question=payload.question, schema_summary=schema)
    if not project.allow_writes:
        assert_read_only(sql)
    return SQLGenerateOut(sql=sql, explanation="", safety_notes="Read-only mode is enabled unless Allow Writes is toggled.")


@app.post("/projects/{project_id}/sql/run", response_model=SQLRunOut)
async def sql_run(project_id: uuid.UUID, payload: SQLRunIn, db: AsyncSession = Depends(get_db), tdb: AsyncSession = Depends(get_target_db)) -> SQLRunOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    if not project.allow_writes:
        assert_read_only(payload.sql)

    res = await tdb.execute(text(payload.sql))
    rows = res.fetchmany(200)
    cols = list(res.keys())
    return SQLRunOut(columns=cols, rows=[list(r) for r in rows], row_count=len(rows))


@app.get("/projects/{project_id}/sql/saved", response_model=list[SavedQueryOut])
async def sql_saved(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[SavedQueryOut]:
    rows = (
        await db.execute(select(SavedQuery).where(SavedQuery.project_id == project_id).order_by(SavedQuery.created_at.desc()))
    ).scalars().all()
    return [SavedQueryOut.model_validate(q, from_attributes=True) for q in rows]


@app.post("/projects/{project_id}/sql/saved", response_model=SavedQueryOut)
async def sql_saved_create(project_id: uuid.UUID, payload: SavedQueryCreate, db: AsyncSession = Depends(get_db)) -> SavedQueryOut:
    q = SavedQuery(project_id=project_id, name=payload.name, sql=payload.sql)
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return SavedQueryOut.model_validate(q, from_attributes=True)


# ---------------- Files ----------------


@app.post("/projects/{project_id}/files/upload", response_model=FileOut)
async def upload_file(project_id: uuid.UUID, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> FileOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    upload_dir = _project_dir(project_id) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_name = os.path.basename(file.filename or "upload")
    dest = upload_dir / safe_name

    content = await file.read()
    dest.write_bytes(content)

    pf = ProjectFile(
        project_id=project_id,
        name=safe_name,
        path=str(dest),
        size_bytes=len(content),
        mime_type=file.content_type,
    )
    db.add(pf)
    await db.commit()
    await db.refresh(pf)
    return FileOut.model_validate(pf, from_attributes=True)


@app.get("/projects/{project_id}/files", response_model=list[FileOut])
async def list_files(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[FileOut]:
    rows = (
        await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id).order_by(ProjectFile.created_at.desc()))
    ).scalars().all()
    return [FileOut.model_validate(f, from_attributes=True) for f in rows]


@app.get("/projects/{project_id}/files/{file_id}/preview", response_model=FilePreviewOut)
async def get_file_preview(project_id: uuid.UUID, file_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> FilePreviewOut:
    pf = await db.get(ProjectFile, file_id)
    if not pf or pf.project_id != project_id:
        raise HTTPException(404, "File not found")

    if pf.preview is None:
        data = await preview_file(pf.path)
        pf.preview = data
        await db.commit()

    return FilePreviewOut(columns=pf.preview.get("columns", []), rows=pf.preview.get("rows", []))


@app.get("/projects/{project_id}/files/{file_id}/profile", response_model=FileProfileOut)
async def get_file_profile(project_id: uuid.UUID, file_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> FileProfileOut:
    pf = await db.get(ProjectFile, file_id)
    if not pf or pf.project_id != project_id:
        raise HTTPException(404, "File not found")

    if pf.profile is None:
        data = await profile_file(pf.path)
        pf.profile = data
        await db.commit()

    return FileProfileOut(profile=pf.profile)


# ---------------- Workspace ----------------


@app.get("/projects/{project_id}/workspace", response_model=list[WorkspaceCellOut])
async def workspace_get(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> list[WorkspaceCellOut]:
    rows = (
        await db.execute(select(WorkspaceCell).where(WorkspaceCell.project_id == project_id).order_by(WorkspaceCell.position.asc()))
    ).scalars().all()
    return [WorkspaceCellOut.model_validate(c, from_attributes=True) for c in rows]


@app.post("/projects/{project_id}/workspace/cells", response_model=WorkspaceCellOut)
async def workspace_add_cell(project_id: uuid.UUID, payload: WorkspaceCellCreate, db: AsyncSession = Depends(get_db)) -> WorkspaceCellOut:
    existing = (
        await db.execute(select(WorkspaceCell).where(WorkspaceCell.project_id == project_id).order_by(WorkspaceCell.position.desc()))
    ).scalars().first()
    pos = payload.position if payload.position is not None else ((existing.position + 1) if existing else 0)

    c = WorkspaceCell(project_id=project_id, type=payload.type, position=pos, source=payload.source)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return WorkspaceCellOut.model_validate(c, from_attributes=True)


@app.patch("/projects/{project_id}/workspace/cells/{cell_id}", response_model=WorkspaceCellOut)
async def workspace_patch_cell(project_id: uuid.UUID, cell_id: uuid.UUID, payload: WorkspaceCellPatch, db: AsyncSession = Depends(get_db)) -> WorkspaceCellOut:
    c = await db.get(WorkspaceCell, cell_id)
    if not c or c.project_id != project_id:
        raise HTTPException(404, "Cell not found")

    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(c, k, v)

    await db.commit()
    await db.refresh(c)
    return WorkspaceCellOut.model_validate(c, from_attributes=True)


@app.post("/projects/{project_id}/workspace/cells/{cell_id}/run", response_model=ExecuteOut)
async def workspace_run_cell(project_id: uuid.UUID, cell_id: uuid.UUID, db: AsyncSession = Depends(get_db), tdb: AsyncSession = Depends(get_target_db)) -> ExecuteOut:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    c = await db.get(WorkspaceCell, cell_id)
    if not c or c.project_id != project_id:
        raise HTTPException(404, "Cell not found")
    return await _run_cell(project, c, db=db, tdb=tdb)


@app.post("/projects/{project_id}/workspace/run_all", response_model=list[ExecuteOut])
async def workspace_run_all(project_id: uuid.UUID, db: AsyncSession = Depends(get_db), tdb: AsyncSession = Depends(get_target_db)) -> list[ExecuteOut]:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    rows = (
        await db.execute(select(WorkspaceCell).where(WorkspaceCell.project_id == project_id).order_by(WorkspaceCell.position.asc()))
    ).scalars().all()
    outs: list[ExecuteOut] = []
    for c in rows:
        if c.type in {CellType.python, CellType.sql}:
            outs.append(await _run_cell(project, c, db=db, tdb=tdb))
    return outs


# ---------------- Export ----------------


@app.post("/projects/{project_id}/export/ipynb")
async def export_ipynb(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> FileResponse:
    import nbformat as nbf

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    rows = (
        await db.execute(select(WorkspaceCell).where(WorkspaceCell.project_id == project_id).order_by(WorkspaceCell.position.asc()))
    ).scalars().all()

    nb = nbf.v4.new_notebook(
        metadata={
            "title": project.name,
            "exported_at": datetime.utcnow().isoformat() + "Z",
            "notes": "Exported from Unified Data App",
        }
    )

    nb.cells.append(
        nbf.v4.new_markdown_cell(
            f"# {project.name}\n\nExported at: {datetime.utcnow().isoformat()}Z\n\nEnvironment notes: executor runs Python 3.12"
        )
    )

    for c in rows:
        if c.type.value == "markdown":
            nb.cells.append(nbf.v4.new_markdown_cell(c.source))
        elif c.type.value == "python":
            cell = nbf.v4.new_code_cell(c.source)
            if c.stdout:
                cell.outputs.append(nbf.v4.new_output("stream", name="stdout", text=c.stdout))
            if c.stderr:
                cell.outputs.append(nbf.v4.new_output("stream", name="stderr", text=c.stderr))
            nb.cells.append(cell)
        elif c.type.value == "sql":
            nb.cells.append(nbf.v4.new_markdown_cell("```sql\n" + c.source + "\n```"))

    export_dir = _project_dir(project_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"{project.name.replace(' ', '_')}_{project_id}.ipynb"
    path.write_text(nbf.writes(nb), encoding="utf-8")

    return FileResponse(str(path), filename=path.name, media_type="application/x-ipynb+json")
