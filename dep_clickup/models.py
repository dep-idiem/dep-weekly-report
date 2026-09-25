"""Tipos de los objetos leidos de ClickUp. Fechas siempre en America/Santiago."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Member:
    id: int
    username: str
    email: str
    role: int | None  # 1 owner, 2 admin, 3 member, 4 guest


@dataclass(frozen=True)
class ListInfo:
    id: str
    name: str
    status: str | None      # estado de la lista (campo "status" de ClickUp), puede venir vacio
    archived: bool
    folder_id: str | None
    space_id: str | None
    task_count: int | None
    assignee_id: int | None = None          # responsable de la lista (el listado del folder no trae id)
    assignee_username: str | None = None
    start: dt.datetime | None = None
    due: dt.datetime | None = None


@dataclass(frozen=True)
class CustomFieldDef:
    id: str
    name: str
    type: str
    type_config: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)


@dataclass(frozen=True)
class CustomField:
    """Valor de un custom field en una tarea, ya resuelto.

    value: dropdown -> etiqueta; labels -> lista de etiquetas; date -> datetime local;
    number/currency -> float; manual_progress -> fraccion 0-1 (ver fields.py); users -> nombres.
    raw: valor tal como vino de la API.
    """
    id: str
    name: str
    type: str
    value: Any
    raw: Any = field(compare=False, hash=False)


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    parent: str | None
    status: str
    list_id: str
    start: dt.datetime | None
    due: dt.datetime | None
    time_estimate_ms: int | None
    assignees: tuple[str, ...]
    custom_fields: dict[str, CustomField]   # por nombre
    date_updated: dt.datetime | None = None
    url: str = ""
    status_type: str = ""       # open / custom / done / closed
    date_created: dt.datetime | None = None

    @property
    def cerrada(self) -> bool:
        """Estado de tipo cerrado en ClickUp: grupos "done" y "closed"."""
        return self.status_type in ("done", "closed")

    @property
    def start_date(self) -> dt.date | None:
        return self.start.date() if self.start else None

    @property
    def due_date(self) -> dt.date | None:
        return self.due.date() if self.due else None

    @property
    def time_estimate_h(self) -> float | None:
        return self.time_estimate_ms / 3_600_000 if self.time_estimate_ms is not None else None

    def cf(self, name: str, default: Any = None) -> Any:
        f = self.custom_fields.get(name)
        return default if f is None or f.value is None else f.value


@dataclass(frozen=True)
class TimeEntry:
    id: str
    user_id: int
    user_name: str
    task_id: str
    task_name: str
    list_id: str
    start: dt.datetime            # local Santiago
    end: dt.datetime | None
    duration_ms: int
    description: str = ""
    updated: dt.datetime | None = None   # campo "at" de la API
    source: str = ""                     # "clickup" (app), "api" (integracion o importacion), ...

    @property
    def date(self) -> dt.date:
        """Fecha de la entrada: fecha local de su start."""
        return self.start.date()

    @property
    def hours(self) -> float:
        return self.duration_ms / 3_600_000
