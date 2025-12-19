from __future__ import annotations

import json
import os
import subprocess
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Executor")


class ExecuteIn(BaseModel):
    code: str
    timeout_s: int = Field(default=60, ge=1, le=300)
    memory_mb: int | None = Field(default=None, ge=64, le=8192)
    disable_network: bool | None = None


class PathIn(BaseModel):
    path: str
    timeout_s: int = Field(default=60, ge=1, le=300)
    n: int = Field(default=20, ge=1, le=200)


def _defaults() -> tuple[int, int, bool]:
    timeout_s = int(os.environ.get("EXECUTOR_DEFAULT_TIMEOUT_S", "60"))
    memory_mb = int(os.environ.get("EXECUTOR_DEFAULT_MEMORY_MB", "1024"))
    disable_network = os.environ.get("EXECUTOR_DISABLE_NETWORK", "true").lower() in {"1", "true", "yes"}
    return timeout_s, memory_mb, disable_network


def _run_runner(payload: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["python", "-m", "app.runner"],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=timeout_s + 2,
        )
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Timeout after {timeout_s}s", "result": None}

    if proc.returncode != 0:
        return {
            "stdout": proc.stdout or "",
            "stderr": (proc.stderr or "")[:8000],
            "result": None,
        }

    try:
        return json.loads(proc.stdout)
    except Exception as e:  # noqa: BLE001
        return {"stdout": proc.stdout or "", "stderr": f"Bad executor JSON: {e}. stderr={proc.stderr}", "result": None}


@app.post("/execute")
def execute(payload: ExecuteIn) -> dict[str, Any]:
    default_timeout, default_mem, default_disable_net = _defaults()
    timeout_s = payload.timeout_s or default_timeout
    memory_mb = payload.memory_mb or default_mem
    disable_network = payload.disable_network if payload.disable_network is not None else default_disable_net

    result = _run_runner(
        {
            "kind": "execute",
            "code": payload.code,
            "timeout_s": timeout_s,
            "memory_mb": memory_mb,
            "disable_network": disable_network,
        },
        timeout_s,
    )
    return result


@app.post("/profile")
def profile(p: PathIn) -> dict[str, Any]:
    if not p.path:
        raise HTTPException(400, "Missing path")

    default_timeout, default_mem, default_disable_net = _defaults()
    result = _run_runner(
        {
            "kind": "profile",
            "path": p.path,
            "timeout_s": p.timeout_s or default_timeout,
            "memory_mb": default_mem,
            "disable_network": default_disable_net,
        },
        p.timeout_s or default_timeout,
    )
    return result.get("result") or {}


@app.post("/preview")
def preview(p: PathIn) -> dict[str, Any]:
    if not p.path:
        raise HTTPException(400, "Missing path")

    default_timeout, default_mem, default_disable_net = _defaults()
    result = _run_runner(
        {
            "kind": "preview",
            "path": p.path,
            "n": p.n,
            "timeout_s": p.timeout_s or default_timeout,
            "memory_mb": default_mem,
            "disable_network": default_disable_net,
        },
        p.timeout_s or default_timeout,
    )
    return result.get("result") or {"columns": [], "rows": []}
