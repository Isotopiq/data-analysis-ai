from __future__ import annotations

from typing import Any

import httpx

from app.models import Project, LLMProvider
from app.secrets import decrypt_str
from app.settings import settings


def _sql_prompt(question: str, schema_summary: str) -> str:
    return (
        "You are a senior data engineer. Convert the user's question into a SINGLE Postgres SQL query. "
        "Return ONLY SQL, no markdown, no explanation.\n\n"
        f"Schema summary:\n{schema_summary}\n\n"
        f"User question: {question}\n\n"
        "Rules:\n"
        "- Prefer SELECT-only.\n"
        "- Use LIMIT 10 by default unless user asks otherwise.\n"
        "- Use fully-qualified table names if schema is known.\n"
    )


async def generate_sql(project: Project, *, question: str, schema_summary: str) -> str:
    prompt = _sql_prompt(question, schema_summary)

    if project.llm_provider == LLMProvider.ollama:
        base = settings.ollama_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{base}/api/generate",
                json={
                    "model": project.llm_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": float(project.llm_temperature)},
                },
            )
            r.raise_for_status()
            data = r.json()
            return (data.get("response") or "").strip()

    # OpenAI-compatible
    base = (project.api_base_url or settings.openai_base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("API LLM base URL not configured")

    api_key = None
    if project.api_key_encrypted:
        api_key = decrypt_str(project.api_key_encrypted)
    elif settings.openai_api_key:
        api_key = settings.openai_api_key

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict[str, Any] = {
        "model": project.llm_model,
        "messages": [
            {"role": "system", "content": "You generate SQL."},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(project.llm_temperature),
    }

    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        r = await client.post(f"{base}/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        return (text or "").strip()
