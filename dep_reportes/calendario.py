"""Dias habiles. Por defecto lunes a viernes sin feriados, igual que NETWORKDAYS del Excel."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterator

UN_DIA = dt.timedelta(days=1)


@dataclass(frozen=True)
class Calendario:
    feriados: frozenset[dt.date] = field(default_factory=frozenset)

    def es_habil(self, d: dt.date) -> bool:
        return d.weekday() < 5 and d not in self.feriados

    def networkdays(self, a: dt.date, b: dt.date) -> int:
        """Como NETWORKDAYS(a, b) de Excel: cuenta ambos extremos; negativo si b < a."""
        if b < a:
            return -self.networkdays(b, a)
        semanas, resto = divmod((b - a).days + 1, 7)
        n = semanas * 5
        d = a + dt.timedelta(days=semanas * 7)
        for _ in range(resto):
            if d.weekday() < 5:
                n += 1
            d += UN_DIA
        if self.feriados:
            n -= sum(1 for f in self.feriados if a <= f <= b and f.weekday() < 5)
        return n

    def dias_habiles(self, a: dt.date, b: dt.date) -> Iterator[dt.date]:
        d = a
        while d <= b:
            if self.es_habil(d):
                yield d
            d += UN_DIA


SIN_FERIADOS = Calendario()


def leer_dias_no_habiles(ruta) -> dict[dt.date, str]:
    """config/dias_no_habiles.csv (fecha,motivo): dias adicionales no habiles de IDIEM."""
    import csv
    from pathlib import Path
    ruta = Path(ruta)
    if not ruta.exists():
        return {}
    with ruta.open(encoding="utf-8-sig", newline="") as f:
        return {dt.date.fromisoformat(r["fecha"].strip()): (r.get("motivo") or "").strip()
                for r in csv.DictReader(f) if (r.get("fecha") or "").strip()}


def calendario_chile(años: range = range(2024, 2031), extra_csv=None) -> Calendario:
    """Lunes a viernes menos feriados de Chile (paquete holidays) y los dias de config/dias_no_habiles.csv."""
    import holidays
    feriados = set(holidays.CL(years=list(años)))
    if extra_csv is not None:
        feriados |= set(leer_dias_no_habiles(extra_csv))
    return Calendario(frozenset(feriados))
