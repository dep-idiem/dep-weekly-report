"""Genera docs/guia_advertencias.md desde dep_reportes.resolucion (fuente unica de la tabla).

Uso: python scripts/guia_advertencias.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dep_reportes import resolucion as RES  # noqa: E402

DESTINO = Path(__file__).resolve().parents[1] / "docs" / "guia_advertencias.md"

# Contexto de ejemplo para mostrar la accion con nombres de relleno.
EJEMPLO = RES.Contexto(tarea="<tarea>", lista="<proyecto>", tiene_linea_base=True,
                       datos={"codigo": "PJ-XXXX", "nombre": "<nombre del proyecto>", "codigo_base": "<código>"})


def _impacto(e: RES.Entrada) -> str:
    if e.impacto_con_lb == e.impacto_sin_lb:
        return e.impacto_con_lb
    return f"{e.impacto_sin_lb} (sin línea base) / {e.impacto_con_lb} (con línea base)"


def _celda(s: str) -> str:
    return s.replace("|", r"\|")


def generar() -> str:
    adm = RES.administracion()
    filas = []
    for tipo, e in RES.CATALOGO.items():
        accion = e.accion(EJEMPLO, adm)
        if e.accion(RES.Contexto(**{**EJEMPLO.__dict__, "tiene_linea_base": False}), adm) != accion:
            accion += " *(Sin línea base: " + e.accion(
                RES.Contexto(**{**EJEMPLO.__dict__, "tiene_linea_base": False}), adm).removeprefix(accion).strip() + ")*"
        quien = adm if e.responsable == RES.ADMIN else e.responsable
        filas.append(f"| `{tipo}` | {_celda(e.significado)} | {_celda(accion)} | {quien} | {_impacto(e)} |")
    pend = [f"| `{t}` | {_celda(s)} | *Pendiente de definir* | — | — |" for t, s in RES.PENDIENTES.items()]
    pend += [f"| `{t}` | {_celda(s)} | *No va a la hoja: solo en calidad_datos.md* | — | — |"
             for t, s in RES.SOLO_CALIDAD.items()]
    return "\n".join([
        "# Guía de advertencias del reporte semanal DEP",
        "",
        "Cada advertencia del reporte indica qué pasa, cómo resolverlo en ClickUp, quién lo resuelve y qué impacto "
        "tiene mientras no se corrija. Este archivo se genera con `python scripts/guia_advertencias.py` "
        "desde `dep_reportes/resolucion.py`; no se edita a mano.",
        "",
        "**Impacto**",
        "",
        f"- **{RES.IMPIDE}**: el proyecto no puede tener línea base o curva S.",
        f"- **{RES.DISTORSIONA}**: hay curva S, pero algún número (avance, HH, proyección) sale mal.",
        f"- **{RES.INFORMATIVA}**: no cambia las cifras; conviene revisarla.",
        "",
        "**Responsable**: JP (jefe de proyecto), " + adm + " o Informativa (no requiere acción).",
        "",
        "En el reporte, `<tarea>` y `<proyecto>` se reemplazan por el nombre real de la tarea o del proyecto.",
        "",
        "| Tipo | Qué significa | Cómo resolverlo | Quién | Impacto |",
        "|---|---|---|---|---|",
        *filas,
        *pend,
        "",
    ])


if __name__ == "__main__":
    DESTINO.write_text(generar(), encoding="utf-8", newline="\n")
    print(f"Escrito {DESTINO}")
