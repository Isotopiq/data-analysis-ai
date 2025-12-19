from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_schema_summary(db: AsyncSession, *, max_tables: int = 50) -> str:
    # Simple, safe information_schema summary.
    q = text(
        """
        select table_schema, table_name, column_name, data_type
        from information_schema.columns
        where table_schema not in ('pg_catalog', 'information_schema')
        order by table_schema, table_name, ordinal_position
        limit :limit
        """
    )
    rows = (await db.execute(q, {"limit": max_tables * 200})).all()
    if not rows:
        return "(no tables found)"

    out_lines: list[str] = []
    cur = None
    cols: list[str] = []
    for schema, table, col, dtype in rows:
        key = f"{schema}.{table}"
        if cur is None:
            cur = key
        if key != cur:
            out_lines.append(f"- {cur}: {', '.join(cols)}")
            cols = []
            cur = key
        cols.append(f"{col} ({dtype})")

    if cur is not None:
        out_lines.append(f"- {cur}: {', '.join(cols)}")

    if len(out_lines) > max_tables:
        out_lines = out_lines[:max_tables] + ["(truncated)"]

    return "\n".join(out_lines)
