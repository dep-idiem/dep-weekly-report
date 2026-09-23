"""Restaura la hoja de reportes desde un respaldo (carpeta reportes/respaldos/<fecha> o artefacto de Actions).

Por defecto solo muestra qué haría. Con --confirmar reescribe en Sheets las pestañas del respaldo, salvo:
- `ejecuciones` (es el registro de corridas: se conserva y se le agrega una fila "restaurado");
- `linea_base` (solo se agregan filas; una corrida fallida solo pudo agregar revisiones nuevas). Usar
  --incluir-linea-base solo si hay que quitar una revisión recién agregada por error.

Uso:
    python scripts/restaurar_respaldo.py --dir reportes/respaldos/20260928T040512
    python scripts/restaurar_respaldo.py --dir <carpeta> --confirmar
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dep_clickup.config import TZ  # noqa: E402
from dep_reportes import esquema as E  # noqa: E402
from dep_reportes.almacen import AlmacenCsv, AlmacenSheets, fusionar  # noqa: E402
from dep_reportes.config_reportes import SHEETS_REPORTES_ID  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--incluir-linea-base", action="store_true")
    ap.add_argument("--confirmar", action="store_true", help="escribe en Sheets (sin esto, solo muestra el plan)")
    a = ap.parse_args()
    respaldo = AlmacenCsv(a.dir).leer()
    if not respaldo:
        print(f"No hay CSV del esquema en {a.dir}")
        return 2
    excluir = {"ejecuciones"} | (set() if a.incluir_linea_base else {"linea_base"})
    tablas = {t: f for t, f in respaldo.items() if t not in excluir}

    sheets = AlmacenSheets(SHEETS_REPORTES_ID)
    actual = sheets.leer(E.TABLAS)
    print(f"Respaldo {a.dir}:")
    for t in E.TABLAS:
        accion = "se restaura" if t in tablas else "no se toca"
        print(f"  {t:<20} hoja={len(actual.get(t, [])):>6}  respaldo={len(respaldo.get(t, [])) if t in respaldo else '-':>6}  {accion}")
    if not a.confirmar:
        print("Nada escrito. Repetir con --confirmar para restaurar.")
        return 0

    ahora = dt.datetime.now(TZ).replace(microsecond=0)
    fila = {"ejecutado_en": ahora, "corte": None, "tipo_corte": None, "modo": "restauracion",
            "n_proyectos": len(tablas.get("proyectos", [])), "n_lineas_base_nuevas": 0,
            "resultado": "restaurado", "detalle_error": f"Restaurado desde {a.dir.name}"}
    tablas["ejecuciones"] = fusionar("ejecuciones", actual.get("ejecuciones", []), [fila], ahora.date())
    sheets.escribir(tablas, [])
    problemas, _ = sheets.verificar_tipos(E.TABLAS)
    if problemas:
        print("ADVERTENCIA de tipos: " + "; ".join(problemas))
        return 1
    print("Restauración escrita y verificada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
