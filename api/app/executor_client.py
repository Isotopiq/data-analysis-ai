from __future__ import annotations

from typing import Any

import httpx

from app.settings import settings


async def execute_python(code: str, *, timeout_s: int = 60) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout_s + 5) as client:
        r = await client.post(
            f"{settings.executor_url}/execute",
            json={"code": code, "timeout_s": timeout_s},
        )
        r.raise_for_status()
        return r.json()


async def profile_file(path: str, *, timeout_s: int = 60) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout_s + 5) as client:
        r = await client.post(
            f"{settings.executor_url}/profile",
            json={"path": path, "timeout_s": timeout_s},
        )
        r.raise_for_status()
        return r.json()


async def preview_file(path: str, *, timeout_s: int = 60, n: int = 20) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout_s + 5) as client:
        r = await client.post(
            f"{settings.executor_url}/preview",
            json={"path": path, "timeout_s": timeout_s, "n": n},
        )
        r.raise_for_status()
        return r.json()
