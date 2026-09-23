"""Convenciones de nombres de listas de ClickUp del DEP."""
from __future__ import annotations

import re

# "PJ-2026.0152 | ...", "PR-2026.0215 | ...", "PJ-2025.0019-0147 | ...", "ADM-006 ..."
LIST_CODE_RE = re.compile(r"^\s*((?:PJ|PR)-\d{4}\.\d{4}(?:-\d{4})?|ADM-\d{3})\b")


def list_code(list_name: str) -> str | None:
    m = LIST_CODE_RE.match(list_name or "")
    return m.group(1) if m else None
