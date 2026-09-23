"""Codigo de proyecto unico y estable por lista.

El codigo base sale del prefijo del nombre de la lista ("PJ-2025.0019-0147 | ..."). Si dos listas
comparten codigo base, cada una recibe un sufijo "-A", "-B", ... (por orden de list_id, que es el orden
de creacion). Una vez asignado, el codigo de una lista se conserva en las corridas siguientes (se lee de
la pestaña `proyectos`), aunque la otra lista desaparezca o se agreguen listas nuevas con el mismo codigo.
"""
from __future__ import annotations

import string
from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence

from dep_clickup.naming import list_code


@dataclass(frozen=True)
class Asignacion:
    codigos: dict[str, str]                 # list_id -> codigo unico
    duplicados: dict[str, list[str]]        # codigo base -> list_ids que lo comparten en ClickUp hoy


def codigo_base(nombre: str, list_id: str) -> str:
    return list_code(nombre) or list_id


def asignar(listas: Sequence[tuple[str, str]], previos: Mapping[str, str]) -> Asignacion:
    """listas: (list_id, nombre) de todas las listas del folder; previos: list_id -> codigo ya publicado."""
    base = {lid: codigo_base(nombre, lid) for lid, nombre in listas}
    por_base: dict[str, list[str]] = defaultdict(list)
    for lid in sorted(base, key=_orden):
        por_base[base[lid]].append(lid)
    duplicados = {b: ids for b, ids in por_base.items() if len(ids) > 1}

    # 1. Se reutiliza el codigo publicado si sigue siendo de esa lista sola y corresponde a su codigo base.
    cuenta_previos = defaultdict(int)
    for c in previos.values():
        cuenta_previos[c] += 1
    codigos: dict[str, str] = {}
    for lid in base:
        c = previos.get(lid)
        # (un codigo publicado para dos listas, como el estado inicial de 0019-0147, no se reutiliza)
        if c and cuenta_previos[c] == 1 and (c == base[lid] or c.startswith(base[lid] + "-")):
            codigos[lid] = c
    usados = set(codigos.values()) | {c for lid, c in previos.items() if lid not in base and cuenta_previos[c] == 1}

    # 2. Listas sin codigo: el base si esta libre y no esta duplicado; si no, base + "-A", "-B", ...
    for b, ids in por_base.items():
        for lid in ids:
            if lid in codigos:
                continue
            if b not in duplicados and b not in usados:
                codigos[lid] = b
            else:
                codigos[lid] = next(f"{b}-{x}" for x in _letras() if f"{b}-{x}" not in usados)
            usados.add(codigos[lid])
    return Asignacion(codigos, duplicados)


def _orden(lid: str):
    return (0, int(lid)) if lid.isdigit() else (1, lid)


def _letras():
    yield from string.ascii_uppercase
    for a in string.ascii_uppercase:
        for b in string.ascii_uppercase:
            yield a + b
