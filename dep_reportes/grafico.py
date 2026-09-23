"""PNG de la curva S para revision visual."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from .metricas import PuntoSerie  # noqa: E402


def curva_s_png(serie: Sequence[PuntoSerie], control: dt.date, fin: dt.date, titulo: str, ruta: Path,
                total_hh: float | None = None, referencia: Sequence[PuntoSerie] | None = None) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=120)
    f = [p.fecha for p in serie]
    ax.plot(f, [p.programadas for p in serie], color="#2a6fdb", lw=2, marker="o", ms=3, label="HH programadas")
    g = [(p.fecha, p.gastadas) for p in serie if p.gastadas is not None]
    if g:
        ax.plot(*zip(*g), color="#d9480f", lw=2, marker="o", ms=3, label="HH gastadas")
    pr = [(p.fecha, p.proyectadas) for p in serie if p.proyectadas is not None]
    if pr:
        ax.plot(*zip(*pr), color="#d9480f", lw=2, ls="--", marker="o", ms=3, label="HH proyectadas")
    if referencia:
        rp = [(p.fecha, p.programadas) for p in referencia]
        ax.plot(*zip(*rp), color="#2a6fdb", lw=0, marker="x", ms=6, alpha=.6, label="Excel (referencia)")
        for attr in ("gastadas", "proyectadas"):
            pts = [(p.fecha, getattr(p, attr)) for p in referencia if getattr(p, attr) is not None]
            if pts:
                ax.plot(*zip(*pts), color="#d9480f", lw=0, marker="x", ms=6, alpha=.6)
    if total_hh:
        ax.axhline(total_hh, color="#888", lw=1, ls=":", label=f"Total HH = {total_hh:g}")
    ax.axvline(control, color="#2b8a3e", lw=1.2, label=f"Control {control:%d-%m-%Y}")
    ax.axvline(fin, color="#862e9c", lw=1.2, label=f"Termino {fin:%d-%m-%Y}")
    ax.set_title(titulo, fontsize=11)
    ax.set_ylabel("HH acumuladas")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d-%m"))
    ax.grid(alpha=.3)
    ax.legend(fontsize=8, loc="upper left")
    fig.autofmt_xdate()
    fig.tight_layout()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ruta)
    plt.close(fig)
    return ruta
