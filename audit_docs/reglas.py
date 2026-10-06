"""Reglas de completitud documental (rules.yaml) y busqueda tolerante de subcarpetas. Sin E/S de red."""
from __future__ import annotations

import datetime as dt
import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

RULES_YAML = Path(__file__).resolve().parent / "rules.yaml"

# Errores tipograficos conocidos (sobre el texto ya normalizado).
TYPOS = {"ecnonomica": "economica", "economia": "economica", "tecnico": "tecnica", "propuest ": "propuesta "}
UMBRAL_APROXIMADO = 0.85

GOOGLE_NATIVOS = {
    "application/vnd.google-apps.document": "(gdoc)",
    "application/vnd.google-apps.spreadsheet": "(gsheet)",
    "application/vnd.google-apps.presentation": "(gslides)",
    "application/vnd.google-apps.shortcut": "(acceso directo)",
    "application/vnd.google-apps.folder": "(carpeta)",
}


def normalizar(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"^(\d)\b", r"0\1", s)  # "4 Oferta" == "04 Oferta"
    return re.sub(r"\s+", " ", s)


def _corregir(s: str) -> str:
    s = normalizar(s) + " "
    for mal, bien in TYPOS.items():
        s = s.replace(mal, bien)
    return s.strip()


def _numero(s: str) -> str | None:
    m = re.match(r"\s*(\d{1,3})\b", s or "")
    return m.group(1).zfill(2) if m else None


def buscar_subcarpeta(esperado: str, carpetas: list[dict]) -> tuple[dict | None, str | None]:
    """Subcarpeta que corresponde a `esperado` entre `carpetas` (dicts con 'name').

    Modo: 'exacto' (mismo nombre), 'normalizado' (difiere en mayusculas/tildes/espacios), 'variante'
    (typo conocido), 'aproximado' (similitud >= UMBRAL_APROXIMADO), 'por_numero' (solo coincide el
    prefijo numerico, p. ej. '03 ...'). (None, None) si no hay ninguna.
    """
    if not carpetas:
        return None, None
    for c in carpetas:
        if c["name"] == esperado:
            return c, "exacto"
    ne = normalizar(esperado)
    for c in carpetas:
        if normalizar(c["name"]) == ne:
            return c, "normalizado"
    ce = _corregir(esperado)
    for c in carpetas:
        if _corregir(c["name"]) == ce:
            return c, "variante"
    puntaje = sorted(((difflib.SequenceMatcher(None, ce, _corregir(c["name"])).ratio(), i)
                      for i, c in enumerate(carpetas)), reverse=True)
    if puntaje[0][0] >= UMBRAL_APROXIMADO:
        return carpetas[puntaje[0][1]], "aproximado"
    num = _numero(esperado)
    mismos = [c for c in carpetas if num and _numero(c["name"]) == num]
    if len(mismos) == 1:
        return mismos[0], "por_numero"
    return None, None


def extension(nombre: str, mime: str = "") -> str:
    if mime in GOOGLE_NATIVOS:
        return GOOGLE_NATIVOS[mime]
    m = re.search(r"\.([A-Za-z0-9]{1,6})$", nombre or "")
    return "." + m.group(1).lower() if m else "(sin extensión)"


def _fecha(v) -> dt.date | None:
    if v in (None, ""):
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))


RE_CODIGO_ARCHIVO = re.compile(r"(\d{4})[.\-_ ](\d{4})")


def codigo_archivo(nombre: str) -> str | None:
    """'PR.DEP.2026-0262 Evaluación.docx' -> '2026.0262' (primer código AAAA.NNNN del nombre)."""
    m = RE_CODIGO_ARCHIVO.search(nombre or "")
    return f"{m.group(1)}.{m.group(2)}" if m else None


@dataclass
class Regla:
    id: str
    descripcion: str
    subcarpeta: str          # clave en Reglas.subcarpetas
    patron: str
    desde_estado: str
    nivel: str = "faltante"              # faltante (cuenta para INCOMPLETO) / advertencia (solo se informa)
    exigir_codigo: bool = False          # el archivo debe llevar el código de la tarea (AAAA.NNNN)
    patron_revisar: str | None = None    # si nada calza con `patron` pero sí con este: cumple, "por revisar"
    pista_subcarpeta: str | None = None  # si no cumple, buscar el mismo patrón ahí e informarlo como pista

    def coincidencias(self, archivos: list[dict], codigo: str | None = None) -> list[str]:
        return self.evaluar(archivos, codigo)["coincidencias"]

    def evaluar(self, archivos: list[dict], codigo: str | None = None) -> dict:
        """coincidencias (calzan y, si se exige, con el código de la tarea), otro_codigo (calzan con el
        patrón pero llevan el código de otra propuesta o ninguno) y por_revisar (calzan con patron_revisar)."""
        r = re.compile(self.patron, re.IGNORECASE)
        calzan = [a["name"] for a in archivos if r.search(a.get("name") or "")]
        coinc, otro = calzan, []
        if self.exigir_codigo and codigo:
            coinc = [n for n in calzan if codigo_archivo(n) == codigo]
            otro = [n for n in calzan if codigo_archivo(n) != codigo]
        revisar = []
        if not coinc and self.patron_revisar:
            rr = re.compile(self.patron_revisar, re.IGNORECASE)
            revisar = [a["name"] for a in archivos if rr.search(a.get("name") or "")]
        return {"coincidencias": coinc, "otro_codigo": otro, "por_revisar": revisar}


@dataclass
class Reglas:
    pipeline_orden: list[str]
    subcarpetas: dict[str, str]
    reglas: list[Regla]
    # estado real de ClickUp (normalizado) -> estado del pipeline. Opcional en el YAML; sin el, un
    # estado real se asocia al del pipeline solo si su nombre normalizado es igual.
    mapa_estados: dict[str, str | None] = field(default_factory=dict)
    # Tareas sin link creadas antes de esta fecha: HISTORICA (fuera de la evaluacion). None = sin corte.
    fecha_inicio_make: dt.date | None = None
    # Alcance de la evaluacion; lo de fuera se inventaria como FUERA_DE_ALCANCE.
    ubicaciones_en_alcance: list[str] = field(default_factory=list)   # prefijos de ruta "Unidad / carpeta"
    tipos_en_alcance: list[str] = field(default_factory=list)          # valores de Tipo DEP; vacio = todos
    # Tareas sin link con código anterior a este (AAAA.NNNN): HISTORICA. None = sin corte.
    codigo_inicio_make: str | None = None
    # Niveles de subcarpetas que se leen dentro de 03/04 (0 = solo archivos directos) y nombres ignorados.
    recursivo: int = 0
    ignorar_subcarpetas: list[str] = field(default_factory=list)

    @classmethod
    def cargar(cls, path: Path = RULES_YAML) -> "Reglas":
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(pipeline_orden=list(d["pipeline_orden"]), subcarpetas=dict(d["subcarpetas"]),
                   reglas=[Regla(**r) for r in d["reglas"]],
                   mapa_estados={normalizar(k): v for k, v in (d.get("mapa_estados") or {}).items()},
                   fecha_inicio_make=_fecha(d.get("fecha_inicio_make")),
                   ubicaciones_en_alcance=list(d.get("ubicaciones_en_alcance") or []),
                   tipos_en_alcance=list(d.get("tipos_en_alcance") or []),
                   codigo_inicio_make=str(d["codigo_inicio_make"]) if d.get("codigo_inicio_make") else None,
                   recursivo=int(d.get("recursivo") or 0),
                   ignorar_subcarpetas=[normalizar(x) for x in d.get("ignorar_subcarpetas") or []])

    def ignorada(self, nombre_subcarpeta: str) -> bool:
        return normalizar(nombre_subcarpeta) in self.ignorar_subcarpetas

    def estado_conocido(self, estado_real: str) -> bool:
        """True si el estado esta en mapa_estados (aunque sea sin reglas) o coincide con el pipeline."""
        return normalizar(estado_real) in self.mapa_estados or self.estado_pipeline(estado_real) is not None

    def ubicacion_en_alcance(self, ruta: str) -> bool:
        return not self.ubicaciones_en_alcance or any(ruta.startswith(u) for u in self.ubicaciones_en_alcance)

    def tipo_en_alcance(self, tipo: str | None) -> bool:
        return not self.tipos_en_alcance or (tipo or "") in self.tipos_en_alcance

    def estado_pipeline(self, estado_real: str) -> str | None:
        n = normalizar(estado_real)
        if n in self.mapa_estados:
            return self.mapa_estados[n]
        for p in self.pipeline_orden:
            if normalizar(p) == n:
                return p
        return None

    def aplicables(self, estado_real: str) -> list[Regla]:
        p = self.estado_pipeline(estado_real)
        if p is None or p not in self.pipeline_orden:
            return []
        pos = self.pipeline_orden.index(p)
        return [r for r in self.reglas if self.pipeline_orden.index(r.desde_estado) <= pos]
