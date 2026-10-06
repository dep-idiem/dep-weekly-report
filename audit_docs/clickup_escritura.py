"""Escrituras en ClickUp para la auditoria documental (Fase 2).

dep_clickup.ClickUpClient sigue siendo de solo lectura (lo usa el worker de reportes). Este modulo
agrega, solo para audit_docs, los POST/PUT/DELETE necesarios, con el mismo limite de peticiones por
minuto y los mismos reintentos ante 429/5xx. Cada escritura devuelve el codigo HTTP para el log.
"""
from __future__ import annotations

import logging
from typing import Any

import requests

from dep_clickup import config
from dep_clickup.client import ClickUpClient, ClickUpError

log = logging.getLogger(__name__)


class ClickUpEscritura(ClickUpClient):
    def _escribir(self, metodo: str, path: str, body: dict | None = None) -> tuple[int, Any]:
        for intento in range(config.MAX_RETRIES + 1):
            self._throttle()
            self.request_count += 1
            self.request_log[f"{metodo} escritura"] += 1
            try:
                r = self.s.request(metodo, config.API_BASE + path, json=body, timeout=60)
            except (requests.ConnectionError, requests.Timeout) as e:
                if intento == config.MAX_RETRIES:
                    raise
                log.warning("Error de red en %s %s (%s); reintento", metodo, path, e)
                self._sleep(2 ** intento)
                continue
            if (r.status_code == 429 or r.status_code >= 500) and intento < config.MAX_RETRIES:
                self._sleep(self._retry_wait(r, intento))
                continue
            if r.status_code not in (200, 201, 204):
                raise ClickUpError(r.status_code, f"{metodo} {path}", r.text)
            try:
                return r.status_code, r.json()
            except ValueError:
                return r.status_code, None
        raise AssertionError("inalcanzable")

    # --- Campos personalizados -----------------------------------------------------------------

    def set_campo(self, task_id: str, field_id: str, valor: Any) -> int:
        return self._escribir("POST", f"/task/{task_id}/field/{field_id}", {"value": valor})[0]

    def borrar_campo(self, task_id: str, field_id: str) -> int:
        return self._escribir("DELETE", f"/task/{task_id}/field/{field_id}")[0]

    # --- Checklists ----------------------------------------------------------------------------

    def crear_checklist(self, task_id: str, nombre: str) -> dict:
        return self._escribir("POST", f"/task/{task_id}/checklist", {"name": nombre})[1]["checklist"]

    def borrar_checklist(self, checklist_id: str) -> int:
        return self._escribir("DELETE", f"/checklist/{checklist_id}")[0]

    def crear_item(self, checklist_id: str, nombre: str) -> dict:
        return self._escribir("POST", f"/checklist/{checklist_id}/checklist_item", {"name": nombre})[1]["checklist"]

    def editar_item(self, checklist_id: str, item_id: str, **cambios) -> dict:
        return self._escribir("PUT", f"/checklist/{checklist_id}/checklist_item/{item_id}", cambios)[1]["checklist"]
