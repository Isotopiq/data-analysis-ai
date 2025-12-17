from __future__ import annotations

import re


_MUTATING = re.compile(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|comment|call)\b", re.IGNORECASE)


def assert_read_only(sql: str) -> None:
    cleaned = sql.strip().strip(";")
    if not cleaned:
        raise ValueError("SQL is empty")

    # Block multiple statements (very rough but effective for v1)
    if ";" in cleaned:
        raise ValueError("Multiple SQL statements are not allowed")

    if _MUTATING.search(cleaned):
        raise ValueError("Write operations are disabled (SELECT-only mode)")

    # Allow common read-only forms
    if not re.match(r"^(select|with|explain)\b", cleaned, flags=re.IGNORECASE):
        raise ValueError("Only SELECT/WITH/EXPLAIN are allowed in read-only mode")
