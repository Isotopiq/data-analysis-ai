from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncio

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_session_token, decode_session_token, hash_password, verify_password
from app.auth_schemas import LoginIn, MeOut
from app.db import engine, get_db
from app.executor_client import execute_python, preview_file, profile_file
from app.llm import chat_with_context, generate_file_suggestions, generate_sql
from app.models import Base, CellType, ChatMessage, ExecStatus, Project, ProjectFile, SavedQuery, User, WorkspaceCell
from app.schema_introspection import get_schema_summary
from app.schemas import (
    ChatMessageCreate,
    ChatMessageOut,
    ExecuteOut,
    FileAnalyzeOut,
    FileAnalysisSuggestion,
    FileOut,
    FilePreviewOut,
    FileProfileOut,
    DBTestOut,
    ProjectCreate,
    ProjectContextOut,
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
from app.secrets import decrypt_str, encrypt_str
from app.settings import settings
from app.sql_safety import assert_read_only
from app.target_db import target_session

app = FastAPI(title="Unified Data App API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
)

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data/projects"))


def _get_user_id(request: Request) -> uuid.UUID:
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(user_id, uuid.UUID):
        raise HTTPException(401, "Not authenticated")
    return user_id


@app.on_event("startup")
async def _startup() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Best-effort lightweight migration for existing DBs
        await conn.execute(text("alter table if exists projects add column if not exists owner_id uuid"))
        await conn.execute(text("alter table if exists projects add column if not exists target_db_url_encrypted bytea"))

    # Ensure a default admin user exists
    from sqlalchemy.ext.asyncio import async_sessionmaker

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        existing = (await db.execute(select(User).where(User.username == settings.admin_username))).scalars().first()
        if not existing:
            u = User(username=settings.admin_username, password_hash=hash_password(settings.admin_password))
            db.add(u)
            await db.commit()


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    path = request.url.path
    if path == "/health" or path.startswith("/auth/"):
        return await call_next(request)

    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        return Response(status_code=401, content="Not authenticated")

    try:
        request.state.user_id = decode_session_token(token)
    except Exception:
        return Response(status_code=401, content="Invalid session")

    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------- Auth ----------------


@app.post("/auth/login", response_model=MeOut)
async def login(payload: LoginIn, response: Response, db: AsyncSession = Depends(get_db)) -> MeOut:
    user = (await db.execute(select(User).where(User.username == payload.username))).scalars().first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")

    token = create_session_token(user_id=user.id)
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=int(settings.auth_token_ttl_minutes) * 60,
        path="/",
    )
    return MeOut(id=str(user.id), username=user.username)


@app.post("/auth/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(settings.auth_cookie_name, path="/")
    return {"status": "ok"}


@app.get("/auth/me", response_model=MeOut)
async def me(request: Request, db: AsyncSession = Depends(get_db)) -> MeOut:
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise HTTPException(401, "Not authenticated")
    user_id = decode_session_token(token)
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Invalid session")
    return MeOut(id=str(user.id), username=user.username)


def _project_dir(project_id: uuid.UUID) -> Path:
    return DATA_ROOT / str(project_id)


def _project_target_url(project: Project) -> str | None:
    return decrypt_str(project.target_db_url_encrypted) if project.target_db_url_encrypted else None


def _sse(data: str, event: str | None = None) -> str:
    # Minimal Server-Sent Events formatting.
    out = ""
    if event:
        out += f"event: {event}\n"
    for line in data.splitlines() or [""]:
        out += f"data: {line}\n"
    out += "\n"
    return out


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
async def create_project(payload: ProjectCreate, request: Request, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    user_id = _get_user_id(request)
    p = Project(name=payload.name, owner_id=user_id)
    db.add(p)
    await db.commit()
    await db.refresh(p)
    _project_dir(p.id).mkdir(parents=True, exist_ok=True)
    (_project_dir(p.id) / "uploads").mkdir(parents=True, exist_ok=True)
    out = ProjectOut.model_validate(p, from_attributes=True)
    out.target_db_configured = bool(p.target_db_url_encrypted)
    return out


@app.get("/projects", response_model=list[ProjectOut])
async def list_projects(request: Request, db: AsyncSession = Depends(get_db)) -> list[ProjectOut]:
    user_id = _get_user_id(request)
    rows = (
        await db.execute(select(Project).where(Project.owner_id == user_id).order_by(Project.created_at.desc()))
    ).scalars().all()
    outs: list[ProjectOut] = []
    for p in rows:
        o = ProjectOut.model_validate(p, from_attributes=True)
        o.target_db_configured = bool(p.target_db_url_encrypted)
        outs.append(o)
    return outs


@app.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    user_id = _get_user_id(request)
    p = await db.get(Project, project_id)
    if not p or p.owner_id != user_id:
        raise HTTPException(404, "Project not found")
    out = ProjectOut.model_validate(p, from_attributes=True)
    out.target_db_configured = bool(p.target_db_url_encrypted)
    return out


@app.get("/projects/{project_id}/context", response_model=ProjectContextOut)
async def project_context(
    project_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ProjectContextOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")

    async with target_session(_project_target_url(project)) as tdb:
        schema = await get_schema_summary(tdb)
    files = (
        await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id).order_by(ProjectFile.created_at.desc()))
    ).scalars().all()
    cells = (
        await db.execute(select(WorkspaceCell).where(WorkspaceCell.project_id == project_id).order_by(WorkspaceCell.executed_at.desc().nullslast(), WorkspaceCell.position.desc()).limit(5))
    ).scalars().all()

    return ProjectContextOut(
        schema_summary=schema[:4000],
        files=[FileOut.model_validate(f, from_attributes=True) for f in files[:10]],
        recent_cells=[WorkspaceCellOut.model_validate(c, from_attributes=True) for c in cells],
    )


@app.post("/projects/{project_id}/db/test", response_model=DBTestOut)
async def db_test(project_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> DBTestOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")

    try:
        async with target_session(_project_target_url(project)) as tdb:
            await tdb.execute(text("select 1"))
            schema = await get_schema_summary(tdb)
        return DBTestOut(ok=True, message="Connected", schema_summary=schema[:2000])
    except Exception as e:  # noqa: BLE001
        return DBTestOut(ok=False, message=str(e), schema_summary="")


@app.patch("/projects/{project_id}", response_model=ProjectOut)
async def patch_project(project_id: uuid.UUID, payload: ProjectPatch, request: Request, db: AsyncSession = Depends(get_db)) -> ProjectOut:
    user_id = _get_user_id(request)
    p = await db.get(Project, project_id)
    if not p or p.owner_id != user_id:
        raise HTTPException(404, "Project not found")

    data = payload.model_dump(exclude_unset=True)
    api_key = data.pop("api_key", None)
    target_database_url = data.pop("target_database_url", None)
    for k, v in data.items():
        setattr(p, k, v)

    if api_key is not None:
        p.api_key_encrypted = encrypt_str(api_key) if api_key else None

    if target_database_url is not None:
        p.target_db_url_encrypted = encrypt_str(target_database_url) if target_database_url else None

    p.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(p)
    out = ProjectOut.model_validate(p, from_attributes=True)
    out.target_db_configured = bool(p.target_db_url_encrypted)
    return out


@app.delete("/projects/{project_id}")
async def delete_project(project_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    user_id = _get_user_id(request)
    p = await db.get(Project, project_id)
    if not p or p.owner_id != user_id:
        raise HTTPException(404, "Project not found")
    await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()
    return {"status": "deleted"}


# ---------------- Chat ----------------


@app.get("/projects/{project_id}/chat/history", response_model=list[ChatMessageOut])
async def chat_history(project_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> list[ChatMessageOut]:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")
    rows = (
        await db.execute(
            select(ChatMessage).where(ChatMessage.project_id == project_id).order_by(ChatMessage.created_at.asc())
        )
    ).scalars().all()
    return [ChatMessageOut.model_validate(m, from_attributes=True) for m in rows]


@app.post("/projects/{project_id}/chat", response_model=ChatMessageOut)
async def chat(
    project_id: uuid.UUID,
    payload: ChatMessageCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ChatMessageOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")

    user_msg = ChatMessage(project_id=project_id, role="user", content=payload.message, meta={})
    db.add(user_msg)
    await db.commit()

    # Julius-like: build context and let LLM propose actions; fallback to NL→SQL.
    assistant_text = ""
    meta: dict[str, Any] = {}

    # Context: schema + files + recent cells (lightweight)
    async with target_session(_project_target_url(project)) as tdb:
        schema = await get_schema_summary(tdb)

    files = (
        await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id).order_by(ProjectFile.created_at.desc()).limit(10))
    ).scalars().all()
    cells = (
        await db.execute(select(WorkspaceCell).where(WorkspaceCell.project_id == project_id).order_by(WorkspaceCell.position.desc()).limit(5))
    ).scalars().all()
    ctx = "Postgres schema:\n" + schema[:2000] + "\n\n"
    if files:
        ctx += "Files:\n" + "\n".join([f"- {f.name}" for f in files]) + "\n\n"
    if cells:
        ctx += "Recent workspace cells (sources truncated):\n" + "\n".join([f"- {c.type.value}: {c.source[:200]}" for c in cells]) + "\n"

    try:
        plan = await chat_with_context(project, user_message=payload.message, context=ctx)
        assistant_text = str(plan.get("message", "") or "")
        meta = {
            "actions": plan.get("actions", []) if isinstance(plan.get("actions", []), list) else [],
            "citations": plan.get("citations", []) if isinstance(plan.get("citations", []), list) else [],
        }

        # Optional: if an insert_sql action is present, validate read-only and attach a preview.
        sql = None
        for a in meta["actions"]:
            if isinstance(a, dict) and a.get("type") == "insert_sql" and isinstance(a.get("sql"), str):
                sql = a["sql"]
                break
        if sql:
            if not project.allow_writes:
                assert_read_only(sql)
            async with target_session(_project_target_url(project)) as tdb2:
                res = await tdb2.execute(text(sql))
                rows = res.fetchmany(10)
                cols = list(res.keys())
            assistant_text = assistant_text + "\n\nSQL preview (first 10 rows):\n" + f"Columns: {cols}\nRows: {rows}"

    except Exception:
        # Fallback: old behavior (NL→SQL)
        try:
            sql = await generate_sql(project, question=payload.message, schema_summary=schema)
            if not project.allow_writes:
                assert_read_only(sql)
            async with target_session(_project_target_url(project)) as tdb2:
                res = await tdb2.execute(text(sql))
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
                    {"type": "create_sql_cell", "sql": sql, "run": False},
                ],
                "citations": [{"type": "postgres_schema", "summary": schema[:2000]}],
            }
        except Exception as e:  # noqa: BLE001
            assistant_text = f"I couldn’t generate a response: {e}"
            meta = {"citations": [{"type": "postgres_schema", "summary": schema[:2000]}]}

    assistant_msg = ChatMessage(project_id=project_id, role="assistant", content=assistant_text, meta=meta)
    db.add(assistant_msg)
    await db.commit()
    await db.refresh(assistant_msg)
    return ChatMessageOut.model_validate(assistant_msg, from_attributes=True)


@app.post("/projects/{project_id}/chat/stream")
async def chat_stream(
    project_id: uuid.UUID,
    payload: ChatMessageCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")

    user_msg = ChatMessage(project_id=project_id, role="user", content=payload.message, meta={})
    db.add(user_msg)
    await db.commit()

    # Pre-fetch schema/context once
    async with target_session(_project_target_url(project)) as tdb:
        schema = await get_schema_summary(tdb)

    files = (
        await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id).order_by(ProjectFile.created_at.desc()).limit(10))
    ).scalars().all()
    cells = (
        await db.execute(select(WorkspaceCell).where(WorkspaceCell.project_id == project_id).order_by(WorkspaceCell.position.desc()).limit(5))
    ).scalars().all()
    ctx = "Postgres schema:\n" + schema[:2000] + "\n\n"
    if files:
        ctx += "Files:\n" + "\n".join([f"- {f.name}" for f in files]) + "\n\n"
    if cells:
        ctx += "Recent workspace cells (sources truncated):\n" + "\n".join([f"- {c.type.value}: {c.source[:200]}" for c in cells]) + "\n"

    async def gen() -> Any:
        yield _sse("starting", event="status")
        await asyncio.sleep(0)

        assistant_text = ""
        meta: dict[str, Any] = {}
        try:
            plan = await chat_with_context(project, user_message=payload.message, context=ctx)
            assistant_text = str(plan.get("message", "") or "")
            meta = {
                "actions": plan.get("actions", []) if isinstance(plan.get("actions", []), list) else [],
                "citations": plan.get("citations", []) if isinstance(plan.get("citations", []), list) else [],
            }

            sql = None
            for a in meta["actions"]:
                if isinstance(a, dict) and a.get("type") == "insert_sql" and isinstance(a.get("sql"), str):
                    sql = a["sql"]
                    break
            if sql:
                if not project.allow_writes:
                    assert_read_only(sql)
                async with target_session(_project_target_url(project)) as tdb2:
                    res = await tdb2.execute(text(sql))
                    rows = res.fetchmany(10)
                    cols = list(res.keys())
                assistant_text = assistant_text + "\n\nSQL preview (first 10 rows):\n" + f"Columns: {cols}\nRows: {rows}"
        except Exception as e:  # noqa: BLE001
            assistant_text = f"I couldn’t generate a response: {e}"
            meta = {"citations": [{"type": "postgres_schema", "summary": schema[:2000]}]}

        # Stream content in chunks (v1); can be replaced with true token streaming later.
        for i in range(0, len(assistant_text), 80):
            yield _sse(assistant_text[i : i + 80], event="delta")
            await asyncio.sleep(0)

        assistant_msg = ChatMessage(project_id=project_id, role="assistant", content=assistant_text, meta=meta)
        db.add(assistant_msg)
        await db.commit()

        yield _sse("done", event="status")

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------- SQL ----------------


@app.post("/projects/{project_id}/sql/generate", response_model=SQLGenerateOut)
async def sql_generate(project_id: uuid.UUID, payload: SQLGenerateIn, request: Request, db: AsyncSession = Depends(get_db)) -> SQLGenerateOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")

    async with target_session(_project_target_url(project)) as tdb:
        schema = await get_schema_summary(tdb)
    sql = await generate_sql(project, question=payload.question, schema_summary=schema)
    if not project.allow_writes:
        assert_read_only(sql)
    return SQLGenerateOut(sql=sql, explanation="", safety_notes="Read-only mode is enabled unless Allow Writes is toggled.")


@app.post("/projects/{project_id}/sql/run", response_model=SQLRunOut)
async def sql_run(project_id: uuid.UUID, payload: SQLRunIn, request: Request, db: AsyncSession = Depends(get_db)) -> SQLRunOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")

    if not project.allow_writes:
        assert_read_only(payload.sql)

    async with target_session(_project_target_url(project)) as tdb:
        res = await tdb.execute(text(payload.sql))
        rows = res.fetchmany(200)
        cols = list(res.keys())
        return SQLRunOut(columns=cols, rows=[list(r) for r in rows], row_count=len(rows))


@app.get("/projects/{project_id}/sql/saved", response_model=list[SavedQueryOut])
async def sql_saved(project_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> list[SavedQueryOut]:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")
    rows = (
        await db.execute(select(SavedQuery).where(SavedQuery.project_id == project_id).order_by(SavedQuery.created_at.desc()))
    ).scalars().all()
    return [SavedQueryOut.model_validate(q, from_attributes=True) for q in rows]


@app.post("/projects/{project_id}/sql/saved", response_model=SavedQueryOut)
async def sql_saved_create(project_id: uuid.UUID, payload: SavedQueryCreate, request: Request, db: AsyncSession = Depends(get_db)) -> SavedQueryOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")
    q = SavedQuery(project_id=project_id, name=payload.name, sql=payload.sql)
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return SavedQueryOut.model_validate(q, from_attributes=True)


# ---------------- Files ----------------


@app.post("/projects/{project_id}/files/upload", response_model=FileOut)
async def upload_file(project_id: uuid.UUID, request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db)) -> FileOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
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
async def list_files(project_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> list[FileOut]:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")
    rows = (
        await db.execute(select(ProjectFile).where(ProjectFile.project_id == project_id).order_by(ProjectFile.created_at.desc()))
    ).scalars().all()
    return [FileOut.model_validate(f, from_attributes=True) for f in rows]


@app.get("/projects/{project_id}/files/{file_id}/preview", response_model=FilePreviewOut)
async def get_file_preview(project_id: uuid.UUID, file_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> FilePreviewOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")
    pf = await db.get(ProjectFile, file_id)
    if not pf or pf.project_id != project_id:
        raise HTTPException(404, "File not found")

    if pf.preview is None:
        data = await preview_file(pf.path)
        pf.preview = data
        await db.commit()

    return FilePreviewOut(columns=pf.preview.get("columns", []), rows=pf.preview.get("rows", []))


@app.get("/projects/{project_id}/files/{file_id}/profile", response_model=FileProfileOut)
async def get_file_profile(project_id: uuid.UUID, file_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> FileProfileOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")
    pf = await db.get(ProjectFile, file_id)
    if not pf or pf.project_id != project_id:
        raise HTTPException(404, "File not found")

    if pf.profile is None:
        data = await profile_file(pf.path)
        pf.profile = data
        await db.commit()

    return FileProfileOut(profile=pf.profile)


@app.post("/projects/{project_id}/files/{file_id}/analyze", response_model=FileAnalyzeOut)
async def analyze_file(project_id: uuid.UUID, file_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> FileAnalyzeOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")
    pf = await db.get(ProjectFile, file_id)
    if not pf or pf.project_id != project_id:
        raise HTTPException(404, "File not found")

    # Ensure profile exists (used to pick columns).
    if pf.profile is None:
        pf.profile = await profile_file(pf.path)
        await db.commit()

    profile = pf.profile or {}
    cols = profile.get("columns", []) if isinstance(profile, dict) else []

    numeric: list[str] = []
    categorical: list[str] = []
    for c in cols:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        dtype = str(c.get("dtype", "")).lower()
        if isinstance(name, str) and ("int" in dtype or "float" in dtype or "number" in dtype):
            numeric.append(name)
        if isinstance(name, str) and c.get("top_values"):
            categorical.append(name)

    # Build deterministic suggestions; if LLM is configured, prefer LLM-generated suggestions with fallback.
    read_code = (
        "import pandas as pd\n"
        f"path = {pf.path!r}\n"
        "ext = path.lower().split('.')[-1]\n"
        "if ext in ['csv','tsv']:\n"
        "    df = pd.read_csv(path, sep='\\t' if ext=='tsv' else ',')\n"
        "elif ext in ['xlsx','xls']:\n"
        "    df = pd.read_excel(path)\n"
        "elif ext in ['parquet']:\n"
        "    df = pd.read_parquet(path)\n"
        "else:\n"
        "    raise ValueError('Unsupported file type')\n"
    )

    suggestions: list[FileAnalysisSuggestion] = []

    # Try LLM first (if available) and fall back to deterministic suggestions if parsing fails.
    try:
        profile_summary = str(profile)[:8000]
        llm_out = await generate_file_suggestions(project, filename=pf.name, profile_summary=profile_summary)
        raw_suggestions = llm_out.get("suggestions", [])
        if isinstance(raw_suggestions, list) and raw_suggestions:
            parsed: list[FileAnalysisSuggestion] = []
            for s in raw_suggestions[:8]:
                if not isinstance(s, dict):
                    continue
                title = str(s.get("title", "")).strip()
                if not title:
                    continue
                parsed.append(
                    FileAnalysisSuggestion(
                        title=title,
                        description=str(s.get("description", "") or ""),
                        cell_type=(s.get("cell_type") if s.get("cell_type") in {"python", "markdown"} else "python"),
                        code=str(s.get("code", "") or ""),
                    )
                )
            if parsed:
                return FileAnalyzeOut(suggestions=parsed)
    except Exception:
        pass

    suggestions.append(
        FileAnalysisSuggestion(
            title="Load file and show head()",
            description="Load the uploaded file into a DataFrame and preview rows.",
            code=read_code + "\n__table__ = df.head(20)\n",
        )
    )

    if numeric:
        c0 = numeric[0]
        suggestions.append(
            FileAnalysisSuggestion(
                title=f"Histogram of {c0}",
                description="Distribution of a numeric column.",
                code=read_code
                + f"\nfig = px.histogram(df, x={c0!r})\n__plotly_json__ = fig.to_dict()\n",
            )
        )

    if len(numeric) >= 2:
        x, y = numeric[0], numeric[1]
        suggestions.append(
            FileAnalysisSuggestion(
                title=f"Scatter: {x} vs {y}",
                description="Relationship between two numeric columns.",
                code=read_code
                + f"\nfig = px.scatter(df, x={x!r}, y={y!r})\n__plotly_json__ = fig.to_dict()\n",
            )
        )

    if categorical:
        cat = categorical[0]
        suggestions.append(
            FileAnalysisSuggestion(
                title=f"Top categories of {cat}",
                description="Bar chart of most frequent values.",
                code=read_code
                + f"\ncounts = df[{cat!r}].astype(str).value_counts().head(20).reset_index()\n"
                + "counts.columns = ['value','count']\n"
                + "\nfig = px.bar(counts, x='value', y='count')\n__plotly_json__ = fig.to_dict()\n",
            )
        )

    return FileAnalyzeOut(suggestions=suggestions[:8])


# ---------------- Workspace ----------------


@app.get("/projects/{project_id}/workspace", response_model=list[WorkspaceCellOut])
async def workspace_get(project_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> list[WorkspaceCellOut]:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")
    rows = (
        await db.execute(select(WorkspaceCell).where(WorkspaceCell.project_id == project_id).order_by(WorkspaceCell.position.asc()))
    ).scalars().all()
    return [WorkspaceCellOut.model_validate(c, from_attributes=True) for c in rows]


@app.post("/projects/{project_id}/workspace/cells", response_model=WorkspaceCellOut)
async def workspace_add_cell(project_id: uuid.UUID, payload: WorkspaceCellCreate, request: Request, db: AsyncSession = Depends(get_db)) -> WorkspaceCellOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")
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
async def workspace_patch_cell(project_id: uuid.UUID, cell_id: uuid.UUID, payload: WorkspaceCellPatch, request: Request, db: AsyncSession = Depends(get_db)) -> WorkspaceCellOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")
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
async def workspace_run_cell(project_id: uuid.UUID, cell_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> ExecuteOut:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")

    c = await db.get(WorkspaceCell, cell_id)
    if not c or c.project_id != project_id:
        raise HTTPException(404, "Cell not found")
    async with target_session(_project_target_url(project)) as tdb:
        return await _run_cell(project, c, db=db, tdb=tdb)


@app.post("/projects/{project_id}/workspace/run_all", response_model=list[ExecuteOut])
async def workspace_run_all(project_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> list[ExecuteOut]:
    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
        raise HTTPException(404, "Project not found")

    rows = (
        await db.execute(select(WorkspaceCell).where(WorkspaceCell.project_id == project_id).order_by(WorkspaceCell.position.asc()))
    ).scalars().all()
    outs: list[ExecuteOut] = []
    async with target_session(_project_target_url(project)) as tdb:
        for c in rows:
            if c.type in {CellType.python, CellType.sql}:
                outs.append(await _run_cell(project, c, db=db, tdb=tdb))
    return outs


# ---------------- Export ----------------


@app.post("/projects/{project_id}/export/ipynb")
async def export_ipynb(project_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)) -> FileResponse:
    import nbformat as nbf

    user_id = _get_user_id(request)
    project = await db.get(Project, project_id)
    if not project or project.owner_id != user_id:
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

    def _attach_outputs(nb_cell: Any, ws_cell: WorkspaceCell) -> None:
        # Attach outputs captured by the app so notebooks reopen with results.
        # Supports:
        # - stdout/stderr streams
        # - result.type: text/table/plotly
        if getattr(ws_cell, "stdout", None):
            nb_cell.outputs.append(nbf.v4.new_output("stream", name="stdout", text=ws_cell.stdout))
        if getattr(ws_cell, "stderr", None):
            nb_cell.outputs.append(nbf.v4.new_output("stream", name="stderr", text=ws_cell.stderr))

        result = ws_cell.result or None
        if not isinstance(result, dict):
            return

        rtype = result.get("type")
        if rtype == "text":
            text_out = str(result.get("text", ""))
            nb_cell.outputs.append(
                nbf.v4.new_output(
                    "execute_result",
                    data={"text/plain": text_out},
                    metadata={},
                    execution_count=1,
                )
            )
            return

        if rtype == "table":
            cols = result.get("columns") or []
            rows_ = result.get("rows") or []
            try:
                preview = "Columns: " + ", ".join([str(c) for c in cols]) + "\nRows (first 50):\n" + "\n".join(
                    [str(r) for r in rows_[:50]]
                )
            except Exception:
                preview = str(result)[:4000]

            nb_cell.outputs.append(
                nbf.v4.new_output(
                    "execute_result",
                    data={
                        "text/plain": preview,
                        "application/json": {"columns": cols, "rows": rows_},
                    },
                    metadata={},
                    execution_count=1,
                )
            )
            return

        if rtype == "plotly":
            fig = result.get("figure")
            if isinstance(fig, dict):
                nb_cell.outputs.append(
                    nbf.v4.new_output(
                        "display_data",
                        data={
                            "application/vnd.plotly.v1+json": fig,
                            "text/plain": "Plotly figure",
                        },
                        metadata={},
                    )
                )
            return

    for c in rows:
        if c.type.value == "markdown":
            md = nbf.v4.new_markdown_cell(c.source)
            md.metadata["unified_data_app"] = {
                "cell_id": str(c.id),
                "type": "markdown",
                "position": c.position,
            }
            nb.cells.append(md)
        elif c.type.value == "python":
            cell = nbf.v4.new_code_cell(c.source)
            cell.metadata["unified_data_app"] = {
                "cell_id": str(c.id),
                "type": "python",
                "position": c.position,
                "status": str(c.status),
                "executed_at": c.executed_at.isoformat() + "Z" if c.executed_at else None,
                "runtime_ms": c.runtime_ms,
            }
            _attach_outputs(cell, c)
            nb.cells.append(cell)
        elif c.type.value == "sql":
            # Export SQL as a code cell so results can be embedded.
            sql_cell = nbf.v4.new_code_cell(c.source)
            sql_cell.metadata["unified_data_app"] = {
                "cell_id": str(c.id),
                "type": "sql",
                "position": c.position,
                "status": str(c.status),
                "executed_at": c.executed_at.isoformat() + "Z" if c.executed_at else None,
                "runtime_ms": c.runtime_ms,
            }
            _attach_outputs(sql_cell, c)
            nb.cells.append(sql_cell)

    export_dir = _project_dir(project_id) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"{project.name.replace(' ', '_')}_{project_id}.ipynb"
    path.write_text(nbf.writes(nb), encoding="utf-8")

    return FileResponse(str(path), filename=path.name, media_type="application/x-ipynb+json")
