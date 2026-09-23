"""Modos de calculo.

- legado: reproduce el Excel manual (sin feriados, proyeccion desde el ultimo punto de una grilla <= C,
  tareas "No Aplica" incluidas, sin tratamiento de proyecto vencido). Existe para validar contra el Excel.
- dep (por defecto): feriados de Chile y dias no habiles de IDIEM, proyeccion desde las HH gastadas a C
  (inclusive), serie diaria, "No Aplica" fuera del universo y proyecto vencido al primer habil despues de C.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .calendario import SIN_FERIADOS, Calendario, calendario_chile

DIAS_NO_HABILES_CSV = Path(__file__).resolve().parent.parent / "config" / "dias_no_habiles.csv"


@dataclass(frozen=True)
class Modo:
    nombre: str
    cal: Calendario
    base_en_control: bool        # True: proyeccion desde gastadas a C inclusive; False: grilla <= C (Excel)
    excluir_no_aplica: bool
    vencido_primer_habil: bool   # termino <= C: pendientes atrasadas al primer habil despues de C
    paso_grilla_legado: int = 3  # solo base_en_control=False

    def con(self, **kw) -> "Modo":
        return replace(self, **kw)


LEGADO = Modo("legado", SIN_FERIADOS, base_en_control=False, excluir_no_aplica=False, vencido_primer_habil=False)


def modo_dep(extra_csv: Path | None = DIAS_NO_HABILES_CSV) -> Modo:
    return Modo("dep", calendario_chile(extra_csv=extra_csv), base_en_control=True, excluir_no_aplica=True,
                vencido_primer_habil=True)


def por_nombre(nombre: str) -> Modo:
    if nombre == "legado":
        return LEGADO
    if nombre == "dep":
        return modo_dep()
    raise ValueError(f"Modo desconocido: {nombre}")
