"""PDF del informe para Drive: la misma página en tema claro, A4 apaisado, sin la franja «Detalle» (desglose de horas
por tarea), con Chrome sin ventana. En GitHub (ubuntu) Chrome viene instalado; en local se busca en las rutas de
siempre o en la variable CHROME."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

CSS = """<style>
@page{size:A4 landscape;margin:9mm}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.band.det{display:none}
@media print{
 body{background:#fff;font-size:12px}
 .wrap{max-width:none;padding:0}
 h2{break-after:avoid;margin-top:18px}
 .pc,.kpi,.card,tr{break-inside:avoid}
 table.dt{font-size:10px}
 .tri{grid-template-columns:1fr 1fr 1fr!important}
 .band,.wh{grid-template-columns:90px 1fr!important}
 .kpis{grid-template-columns:repeat(3,1fr)!important}
 .cols2{grid-template-columns:1fr 1.2fr!important}
 .pc{margin-bottom:8px}
 .tri .cell{padding:6px 8px}
}
</style><script>document.documentElement.setAttribute('data-theme','light')</script>"""

RUTAS = [r"C:/Program Files/Google/Chrome/Application/chrome.exe",
         r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"]


def chrome() -> str | None:
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    for nombre in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if ruta := shutil.which(nombre):
            return ruta
    return next((r for r in RUTAS if Path(r).exists()), None)


def para_imprimir(html: str) -> str:
    """Las columnas se fuerzan porque Chrome imprime con el diseño móvil."""
    return html.replace("</head>", CSS + "</head>", 1)


def html_a_pdf(html: str, exe: str | None = None) -> bytes:
    exe = exe or chrome()
    if not exe:
        raise RuntimeError("no se encontró Chrome (definir la variable CHROME)")
    with tempfile.TemporaryDirectory() as tmp:
        fuente, pdf = Path(tmp) / "informe.html", Path(tmp) / "informe.pdf"
        fuente.write_text(para_imprimir(html), encoding="utf-8")
        r = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-sandbox", f"--user-data-dir={tmp}/perfil",
                            "--no-pdf-header-footer", "--virtual-time-budget=5000", f"--print-to-pdf={pdf}",
                            fuente.as_uri()], capture_output=True, timeout=180)
        if not pdf.exists() or pdf.stat().st_size == 0:
            raise RuntimeError(f"Chrome no generó el PDF (código {r.returncode}): {r.stderr.decode(errors='replace')[-300:]}")
        return pdf.read_bytes()
