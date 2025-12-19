from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import traceback
from typing import Any


def _apply_limits(*, memory_mb: int, disable_network: bool) -> None:
    # Memory cap (best-effort on Linux)
    try:
        import resource

        bytes_limit = int(memory_mb) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (bytes_limit, bytes_limit))
    except Exception:
        pass

    if disable_network:
        try:
            import socket

            def _blocked(*_a: Any, **_kw: Any) -> Any:
                raise RuntimeError("Outbound network is disabled in the executor")

            socket.socket = _blocked  # type: ignore[assignment]
            socket.create_connection = _blocked  # type: ignore[assignment]
        except Exception:
            pass


def _load_df(path: str):
    import pandas as pd

    ext = os.path.splitext(path.lower())[1]
    if ext in {".csv", ".tsv"}:
        sep = "\t" if ext == ".tsv" else ","
        return pd.read_csv(path, sep=sep)
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if ext in {".parquet"}:
        return pd.read_parquet(path)
    raise ValueError(f"Unsupported file type: {ext}")


def _profile_df(df) -> dict[str, Any]:
    import pandas as pd

    profile: dict[str, Any] = {
        "n_rows": int(df.shape[0]),
        "n_cols": int(df.shape[1]),
        "columns": [],
    }

    for col in df.columns:
        s = df[col]
        missing = int(s.isna().sum())
        col_info: dict[str, Any] = {
            "name": str(col),
            "dtype": str(s.dtype),
            "missing": missing,
            "missing_pct": float(missing / max(1, len(s))),
        }

        if pd.api.types.is_numeric_dtype(s):
            desc = s.describe()
            col_info.update(
                {
                    "min": None if desc.get("min") is None else float(desc.get("min")),
                    "max": None if desc.get("max") is None else float(desc.get("max")),
                    "mean": None if desc.get("mean") is None else float(desc.get("mean")),
                    "std": None if desc.get("std") is None else float(desc.get("std")) if not pd.isna(desc.get("std")) else None,
                }
            )
        else:
            vc = s.astype(str).value_counts(dropna=True).head(10)
            col_info["top_values"] = [{"value": k, "count": int(v)} for k, v in vc.items()]

        profile["columns"].append(col_info)

    return profile


def _df_preview(df, n: int) -> dict[str, Any]:
    head = df.head(n)
    return {
        "columns": [str(c) for c in head.columns.tolist()],
        "rows": [[None if _is_na(x) else x for x in row] for row in head.to_numpy().tolist()],
    }


def _is_na(x: Any) -> bool:
    try:
        import pandas as pd

        return bool(pd.isna(x))
    except Exception:
        return x is None


def _execute_user_code(code: str) -> dict[str, Any]:
    # Provide common data stack imports.
    g: dict[str, Any] = {}
    try:
        import pandas as pd
        import numpy as np
        import plotly.express as px
        import plotly.graph_objects as go

        g.update({"pd": pd, "np": np, "px": px, "go": go})
    except Exception:
        pass

    out = io.StringIO()
    err = io.StringIO()
    result: dict[str, Any] | None = None

    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        exec(code, g, g)  # noqa: S102

    if "__plotly_json__" in g and isinstance(g["__plotly_json__"], dict):
        result = {"type": "plotly", "figure": g["__plotly_json__"]}
    elif "__table__" in g:
        try:
            import pandas as pd

            if isinstance(g["__table__"], pd.DataFrame):
                df = g["__table__"]
                result = {
                    "type": "table",
                    "columns": [str(c) for c in df.columns.tolist()],
                    "rows": df.head(500).to_numpy().tolist(),
                }
        except Exception:
            result = None
    elif "__text__" in g and isinstance(g["__text__"], str):
        result = {"type": "text", "text": g["__text__"]}

    return {"stdout": out.getvalue(), "stderr": err.getvalue(), "result": result}


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    kind = payload.get("kind")
    timeout_s = int(payload.get("timeout_s") or 60)
    memory_mb = int(payload.get("memory_mb") or 1024)
    disable_network = bool(payload.get("disable_network", True))

    _apply_limits(memory_mb=memory_mb, disable_network=disable_network)

    try:
        if kind == "execute":
            code = str(payload.get("code") or "")
            out = _execute_user_code(code)
            print(json.dumps(out))
            return

        if kind == "profile":
            path = str(payload.get("path") or "")
            df = _load_df(path)
            print(json.dumps({"stdout": "", "stderr": "", "result": _profile_df(df)}))
            return

        if kind == "preview":
            path = str(payload.get("path") or "")
            n = int(payload.get("n") or 20)
            df = _load_df(path)
            print(json.dumps({"stdout": "", "stderr": "", "result": _df_preview(df, n)}))
            return

        print(json.dumps({"stdout": "", "stderr": f"Unknown kind: {kind}", "result": None}))

    except Exception:
        print(
            json.dumps(
                {
                    "stdout": "",
                    "stderr": traceback.format_exc()[:8000],
                    "result": None,
                }
            )
        )


if __name__ == "__main__":
    main()
