"""Resolucion de custom fields de ClickUp a valores utiles, por nombre."""
from __future__ import annotations

from typing import Any

from .dates import ms_to_local
from .models import CustomField


def _option_label(type_config: dict, raw: Any) -> Any:
    """Dropdown: el valor puede venir como orderindex (int) o como id de opcion (str)."""
    options = type_config.get("options") or []
    for opt in options:
        if raw == opt.get("id"):
            return opt.get("name") or opt.get("label")
    for opt in options:
        oi = opt.get("orderindex")
        if oi is not None and str(raw) == str(oi):
            return opt.get("name") or opt.get("label")
    return None


def _label_names(type_config: dict, raw: Any) -> list[str]:
    options = {o.get("id"): (o.get("label") or o.get("name")) for o in type_config.get("options") or []}
    return [options.get(x, str(x)) for x in raw or []]


def _to_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def progress_fraction(raw: Any, type_config: dict | None = None) -> float | None:
    """manual_progress / automatic_progress -> fraccion 0-1.

    Verificado en la API (2026-09-23): value = {"current": "100", "percent_completed": 1} con
    type_config = {"start": 0, "end": 100}. `current` va en la escala del campo (0-100) y
    `percent_completed` ya es fraccion 0-1. Se usa (current - start) / (end - start); si falta
    `current`, percent_completed.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        cur = _to_float(raw.get("current"))
        if cur is None:
            return _to_float(raw.get("percent_completed"))
        tc = type_config or {}
        tc = tc.get("tracking") or tc
        start = _to_float(tc.get("start")) or 0.0
        end = _to_float(tc.get("end"))
        if end is None:
            end = 100.0
        return (cur - start) / (end - start) if end != start else None
    v = _to_float(raw)
    return None if v is None else v / 100


def resolve_value(ftype: str, type_config: dict, raw: Any) -> Any:
    if raw is None or raw == "" or raw == []:
        return None
    if ftype == "drop_down":
        return _option_label(type_config, raw)
    if ftype == "labels":
        return _label_names(type_config, raw)
    if ftype == "date":
        return ms_to_local(raw)
    if ftype in ("number", "currency", "emoji"):
        return _to_float(raw)
    if ftype in ("manual_progress", "automatic_progress"):
        return progress_fraction(raw, type_config)
    if ftype == "users":
        return [u.get("username") or u.get("email") or str(u.get("id")) for u in raw]
    if ftype == "checkbox":
        return str(raw).lower() in ("true", "1")
    if ftype in ("tasks", "list_relationship"):
        return [t.get("name") or t.get("id") for t in raw]
    return raw


def resolve_custom_fields(raw_fields: list[dict]) -> dict[str, CustomField]:
    """Lista de custom_fields de una tarea -> {nombre: CustomField}. Se incluyen tambien los vacios."""
    out: dict[str, CustomField] = {}
    for f in raw_fields or []:
        ftype = f.get("type", "")
        tc = f.get("type_config") or {}
        raw = f.get("value")
        out[f.get("name", f.get("id", ""))] = CustomField(
            id=f.get("id", ""), name=f.get("name", ""), type=ftype,
            value=resolve_value(ftype, tc, raw), raw=raw,
        )
    return out
