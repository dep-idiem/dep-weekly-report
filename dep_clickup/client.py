"""Cliente de solo lectura para la API v2 de ClickUp.

- Solo GET: no hay ningun metodo que escriba.
- Limite de 100 peticiones/min por token: ventana deslizante local y, ante 429, espera hasta
  X-RateLimit-Reset (o backoff) y reintenta.
"""
from __future__ import annotations

import collections
import datetime as dt
import logging
import time
from typing import Any, Iterable

import requests

from . import config
from .dates import local_day_bounds_ms, ms_to_local
from .fields import resolve_custom_fields
from .models import CustomFieldDef, ListInfo, Member, Task, TimeEntry

log = logging.getLogger(__name__)


class ClickUpError(RuntimeError):
    def __init__(self, status: int, path: str, body: str):
        super().__init__(f"ClickUp {status} en GET {path}: {body[:500]}")
        self.status = status
        self.path = path
        self.body = body


class ClickUpClient:
    def __init__(self, token: str | None = None, *, max_per_min: int = config.MAX_REQUESTS_PER_MIN,
                 session: requests.Session | None = None, sleep=time.sleep, clock=time.monotonic):
        self.s = session or requests.Session()
        self.s.headers["Authorization"] = token or config.api_token()
        self.max_per_min = max_per_min
        self._sleep = sleep
        self._clock = clock
        self._sent: collections.deque[float] = collections.deque()
        self.request_count = 0          # peticiones HTTP efectivas (incluye reintentos)
        self.request_log: collections.Counter[str] = collections.Counter()  # por endpoint
        self._team_cache: dict | None = None

    # --- HTTP ---------------------------------------------------------------------------------

    def _throttle(self) -> None:
        now = self._clock()
        while self._sent and now - self._sent[0] >= 60:
            self._sent.popleft()
        if len(self._sent) >= self.max_per_min:
            wait = 60 - (now - self._sent[0]) + 0.1
            log.info("Limite local de %s req/min: esperando %.1f s", self.max_per_min, wait)
            self._sleep(wait)
        self._sent.append(self._clock())

    def get(self, path: str, params: dict[str, Any] | list[tuple[str, Any]] | None = None) -> dict:
        kind = "/".join("{id}" if any(ch.isdigit() for ch in seg) else seg for seg in path.split("/"))
        for attempt in range(config.MAX_RETRIES + 1):
            self._throttle()
            self.request_count += 1
            self.request_log[kind] += 1
            try:
                r = self.s.get(config.API_BASE + path, params=params, timeout=60)
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt == config.MAX_RETRIES:
                    raise
                wait = 2 ** attempt
                log.warning("Error de red en %s (%s); reintento en %s s", path, e, wait)
                self._sleep(wait)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == config.MAX_RETRIES:
                    raise ClickUpError(r.status_code, path, r.text)
                wait = self._retry_wait(r, attempt)
                log.warning("HTTP %s en %s; reintento en %.1f s", r.status_code, path, wait)
                self._sleep(wait)
                continue
            if r.status_code != 200:
                raise ClickUpError(r.status_code, path, r.text)
            return r.json()
        raise AssertionError("inalcanzable")

    @staticmethod
    def _retry_wait(r: requests.Response, attempt: int) -> float:
        reset = r.headers.get("X-RateLimit-Reset")
        if r.status_code == 429 and reset:
            try:
                return max(1.0, float(reset) - time.time() + 1)
            except ValueError:
                pass
        return float(min(60, 2 ** (attempt + 1)))

    # --- Workspace ----------------------------------------------------------------------------

    def _teams(self) -> dict:
        if self._team_cache is None:
            self._team_cache = self.get("/team")
        return self._team_cache

    def get_team_id(self) -> str:
        teams = self._teams()["teams"]
        if len(teams) != 1:
            names = ", ".join(f"{t['id']} ({t['name']})" for t in teams)
            raise RuntimeError(f"El token ve {len(teams)} workspaces: {names}. Elegir uno explicitamente.")
        return str(teams[0]["id"])

    def list_members(self, team_id: str | None = None) -> list[Member]:
        team_id = team_id or self.get_team_id()
        for t in self._teams()["teams"]:
            if str(t["id"]) == str(team_id):
                return [Member(id=int(m["user"]["id"]), username=m["user"].get("username") or "",
                               email=(m["user"].get("email") or "").lower(), role=m["user"].get("role"))
                        for m in t.get("members", [])]
        raise RuntimeError(f"Workspace {team_id} no visible con este token")

    # --- Listas y campos ----------------------------------------------------------------------

    def list_lists(self, folder_id: str, include_archived: bool = False) -> list[ListInfo]:
        out = []
        for archived in ([False, True] if include_archived else [False]):
            data = self.get(f"/folder/{folder_id}/list", {"archived": str(archived).lower()})
            for l in data.get("lists", []):
                out.append(parse_list(l, folder_id, archived))
        return out

    def get_list(self, list_id: str) -> dict:
        return self.get(f"/list/{list_id}")

    def get_list_info(self, list_id: str) -> ListInfo:
        return parse_list(self.get_list(list_id))

    def get_list_custom_fields(self, list_id: str) -> list[CustomFieldDef]:
        data = self.get(f"/list/{list_id}/field")
        return [CustomFieldDef(id=f["id"], name=f.get("name", ""), type=f.get("type", ""),
                               type_config=f.get("type_config") or {}) for f in data.get("fields", [])]

    # --- Tareas -------------------------------------------------------------------------------

    def list_tasks_raw(self, list_id: str, include_subtasks: bool = True,
                       include_closed: bool = True) -> list[dict]:
        tasks: list[dict] = []
        page = 0
        while True:
            data = self.get(f"/list/{list_id}/task", {
                "page": page,
                "subtasks": str(include_subtasks).lower(),
                "include_closed": str(include_closed).lower(),
                "archived": "false",
            })
            batch = data.get("tasks", [])
            tasks.extend(batch)
            if data.get("last_page", True) or not batch:
                return tasks
            page += 1

    def list_tasks(self, list_id: str, include_subtasks: bool = True,
                   include_closed: bool = True) -> list[Task]:
        return [parse_task(t, list_id) for t in self.list_tasks_raw(list_id, include_subtasks, include_closed)]

    def get_task(self, task_id: str) -> Task:
        t = self.get(f"/task/{task_id}")
        return parse_task(t, str((t.get("list") or {}).get("id", "")))

    # --- Entradas de tiempo -------------------------------------------------------------------

    def list_time_entries(self, start: dt.date, end: dt.date, list_id: str | None = None,
                          assignees: Iterable[int] | None = None, team_id: str | None = None,
                          folder_id: str | None = None, space_id: str | None = None) -> list[TimeEntry]:
        """Como list_time_entries_raw, ya convertidas (sin cronometros corriendo)."""
        raw = self.list_time_entries_raw(start, end, list_id, assignees, team_id, folder_id, space_id)
        return [e for e in (parse_time_entry(x) for x in raw) if e is not None]

    def list_time_entries_raw(self, start: dt.date, end: dt.date, list_id: str | None = None,
                              assignees: Iterable[int] | None = None, team_id: str | None = None,
                              folder_id: str | None = None, space_id: str | None = None) -> list[dict]:
        """Entradas con start entre start y end (fechas locales de Santiago, ambos incluidos).

        Sin `assignee` el endpoint devuelve solo las del dueño del token; por eso, si no se pasan
        assignees, se consulta con todos los miembros del workspace. ClickUp acepta un solo filtro de
        ubicacion (list_id, folder_id o space_id).
        """
        if sum(x is not None for x in (list_id, folder_id, space_id)) > 1:
            raise ValueError("Solo un filtro de ubicacion: list_id, folder_id o space_id")
        team_id = team_id or self.get_team_id()
        if assignees is None:
            assignees = [m.id for m in self.list_members(team_id)]
        t0, t1 = local_day_bounds_ms(start, end)
        params: dict[str, Any] = {
            "start_date": t0, "end_date": t1,
            "assignee": ",".join(str(a) for a in assignees),
            "include_location_names": "true",
        }
        for k, v in (("list_id", list_id), ("folder_id", folder_id), ("space_id", space_id)):
            if v:
                params[k] = v
        return self.get(f"/team/{team_id}/time_entries", params).get("data", [])


def parse_list(l: dict, folder_id: str | None = None, archived: bool = False) -> ListInfo:
    st = l.get("status")
    asg = l.get("assignee") or {}
    return ListInfo(
        id=str(l["id"]), name=l.get("name", ""),
        status=(st or {}).get("status") if isinstance(st, dict) else st,
        archived=bool(l.get("archived", archived)),
        folder_id=str((l.get("folder") or {}).get("id") or folder_id or "") or None,
        space_id=str((l.get("space") or {}).get("id") or "") or None,
        task_count=l.get("task_count"),
        assignee_id=int(asg["id"]) if asg.get("id") else None,
        assignee_username=asg.get("username") or None,
        start=ms_to_local(l.get("start_date")),
        due=ms_to_local(l.get("due_date")),
    )


def parse_task(t: dict, list_id: str = "") -> Task:
    return Task(
        id=t["id"],
        name=t.get("name", ""),
        parent=t.get("parent"),
        status=((t.get("status") or {}).get("status") or ""),
        list_id=str((t.get("list") or {}).get("id") or list_id),
        start=ms_to_local(t.get("start_date")),
        due=ms_to_local(t.get("due_date")),
        time_estimate_ms=int(t["time_estimate"]) if t.get("time_estimate") not in (None, "") else None,
        assignees=tuple(a.get("username") or a.get("email") or str(a.get("id")) for a in t.get("assignees", [])),
        custom_fields=resolve_custom_fields(t.get("custom_fields", [])),
        date_updated=ms_to_local(t.get("date_updated")),
        url=t.get("url", ""),
        status_type=((t.get("status") or {}).get("type") or ""),
    )


def parse_time_entry(e: dict) -> TimeEntry | None:
    dur = int(e.get("duration") or 0)
    if dur < 0:
        return None  # cronometro corriendo
    task = e.get("task") or {}
    if not isinstance(task, dict):
        task = {}
    loc = e.get("task_location") or {}
    return TimeEntry(
        id=str(e["id"]),
        user_id=int(e["user"]["id"]),
        user_name=e["user"].get("username") or "",
        task_id=task.get("id", ""),
        task_name=task.get("name", ""),
        list_id=str(loc.get("list_id") or ""),
        start=ms_to_local(e["start"]),
        end=ms_to_local(e.get("end")),
        duration_ms=dur,
        description=e.get("description") or "",
        updated=ms_to_local(e.get("at")),
        source=e.get("source") or "",
    )
