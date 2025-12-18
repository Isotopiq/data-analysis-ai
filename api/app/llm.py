from __future__ import annotations

import json
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


def _file_suggestions_prompt(*, filename: str, profile_summary: str) -> str:
    return (
        "You are a data analyst assistant. Propose 3-8 useful analyses/plots for the uploaded dataset. "
        "Return ONLY valid JSON (no markdown). The JSON must be an object with key 'suggestions', "
        "where suggestions is a list of objects with keys: title, description, cell_type, code.\n\n"
        "Constraints:\n"
        "- cell_type must be 'python' or 'markdown'\n"
        "- code must be runnable Python using pandas + plotly (px/go). Use __table__ for DataFrame previews "
        "and __plotly_json__ = fig.to_dict() for plots.\n"
        "- Do not require network access.\n\n"
        f"Filename: {filename}\n\n"
        f"Profile summary:\n{profile_summary}\n"
    )


async def generate_file_suggestions(project: Project, *, filename: str, profile_summary: str) -> dict[str, Any]:
    prompt = _file_suggestions_prompt(filename=filename, profile_summary=profile_summary)

    if project.llm_provider == LLMProvider.ollama:
        base = settings.ollama_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"{base}/api/generate",
                json={
                    "model": project.llm_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": float(project.llm_temperature)},
                },
            )
            r.raise_for_status()
            data = r.json()
            raw = (data.get("response") or "").strip()
            return json.loads(raw)

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
            {"role": "system", "content": "You generate JSON for data analysis suggestions."},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(project.llm_temperature),
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        r = await client.post(f"{base}/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        return json.loads(text)


def _chat_prompt(*, user_message: str, context: str) -> str:
    return (
        "You are a Julius-like data assistant inside a unified data app.\n"
        "You will receive PROJECT CONTEXT and a USER MESSAGE.\n\n"
        "Return ONLY valid JSON (no markdown) with this shape:\n"
        "{\n"
        "  \"message\": \"assistant response text\",\n"
        "  \"actions\": [\n"
        "    {\"type\": \"insert_sql\", \"sql\": \"...\"},\n"
        "    {\"type\": \"create_sql_cell\", \"sql\": \"...\", \"run\": true|false},\n"
        "    {\"type\": \"save_query\", \"name\": \"...\", \"sql\": \"...\"},\n"
        "    {\"type\": \"create_python_cell\", \"code\": \"...\", \"run\": true|false}\n"
        "  ],\n"
        "  \"citations\": [\n"
        "    {\"type\": \"postgres_schema\", \"summary\": \"...\"},\n"
        "    {\"type\": \"file\", \"name\": \"...\", \"summary\": \"...\"}\n"
        "  ]\n"
        "}\n\n"
        "Rules:\n"
        "- Prefer concrete, runnable code.\n"
        "- If generating SQL, keep it read-only (SELECT/WITH) unless the user explicitly requests writes.\n"
        "- Keep citations concise.\n\n"
        f"PROJECT CONTEXT:\n{context}\n\n"
        f"USER MESSAGE:\n{user_message}\n"
    )


async def chat_with_context(project: Project, *, user_message: str, context: str) -> dict[str, Any]:
    prompt = _chat_prompt(user_message=user_message, context=context)

    if project.llm_provider == LLMProvider.ollama:
        base = settings.ollama_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                f"{base}/api/generate",
                json={
                    "model": project.llm_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": float(project.llm_temperature)},
                },
            )
            r.raise_for_status()
            data = r.json()
            raw = (data.get("response") or "").strip()
            return json.loads(raw)

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
            {"role": "system", "content": "You are a Julius-like assistant returning JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(project.llm_temperature),
        "response_format": {"type": "json_object"},
    }

    async with httpx.AsyncClient(timeout=90, headers=headers) as client:
        r = await client.post(f"{base}/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        return json.loads(text)
