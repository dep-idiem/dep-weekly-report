"""Conversion de fechas de ClickUp (epoch en ms, UTC) a America/Santiago."""
from __future__ import annotations

import datetime as dt

from .config import TZ


def ms_to_local(ms: int | str | None) -> dt.datetime | None:
    """Epoch ms UTC -> datetime con zona America/Santiago. None/'' -> None."""
    if ms is None or ms == "":
        return None
    return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc).astimezone(TZ)


def ms_to_local_date(ms: int | str | None) -> dt.date | None:
    """Fecha local (Santiago) del instante. Asi se fecha una entrada de tiempo: por la fecha local de su start."""
    t = ms_to_local(ms)
    return t.date() if t else None


def local_day_bounds_ms(start: dt.date, end: dt.date) -> tuple[int, int]:
    """[inicio de start, fin de end] en hora de Santiago, como epoch ms (ambos dias incluidos)."""
    t0 = dt.datetime.combine(start, dt.time(0), TZ)
    t1 = dt.datetime.combine(end + dt.timedelta(days=1), dt.time(0), TZ)
    return int(t0.timestamp() * 1000), int(t1.timestamp() * 1000) - 1
