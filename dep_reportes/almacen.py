"""Almacen de los reportes: Google Sheets (escritura real) o CSV locales (dry-run).

Escritura en Sheets, pensada para pocas peticiones y sin perder historial:
1. spreadsheets.batchUpdate: crea pestañas faltantes, ajusta el tamaño de la grilla y aplica formato de
   fecha a las columnas de fecha (una sola peticion para todas las pestañas).
2. values.batchUpdate (RAW) con el contenido completo de cada pestaña que cambia (una sola peticion).
   linea_base solo recibe filas nuevas, debajo de las existentes.
3. values.batchClear solo de las filas sobrantes al final (si una tabla quedo mas corta).
Se escribe antes de limpiar: si algo falla a mitad, no se pierden filas historicas.
"""
from __future__ import annotations

import csv
import datetime as dt
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

from dep_clickup.config import TZ

from . import esquema as E, presentacion as PR

EPOCA = dt.date(1899, 12, 30)
FORMATO = {E.FECHA: ("DATE", "yyyy-mm-dd"), E.FECHA_HORA: ("DATE_TIME", "yyyy-mm-dd hh:mm:ss")}


# --- Conversiones -------------------------------------------------------------------------------

def a_serial(v) -> float | int | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        if v.tzinfo:
            v = v.astimezone(TZ).replace(tzinfo=None)
        delta = v - dt.datetime.combine(EPOCA, dt.time())
        return round(delta.days + delta.seconds / 86400, 8)
    return (v - EPOCA).days


def desde_serial(x, tipo: str):
    if x in (None, ""):
        return None
    if tipo == E.FECHA:
        return EPOCA + dt.timedelta(days=int(float(x)))
    # El serial trae ~1 ms de error de redondeo: se lleva al segundo mas cercano.
    return (dt.datetime.combine(EPOCA, dt.time()) + dt.timedelta(seconds=round(float(x) * 86400))).replace(tzinfo=TZ)


def celda_sheets(v, tipo: str):
    """Valor para values.update con valueInputOption=RAW."""
    if v is None:
        return ""
    if tipo in (E.FECHA, E.FECHA_HORA):
        return a_serial(v)
    if tipo == E.ENTERO:
        return int(v)
    if tipo == E.NUMERO:
        return float(v)
    if tipo == E.BOOLEANO:
        return bool(v)
    return str(v)


def celda_csv(v, tipo: str) -> str:
    if v is None:
        return ""
    if tipo == E.FECHA:
        return v.isoformat()
    if tipo == E.FECHA_HORA:
        return v.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S") if v.tzinfo else v.strftime("%Y-%m-%d %H:%M:%S")
    if tipo == E.NUMERO:
        return repr(float(v))
    if tipo == E.BOOLEANO:
        return "TRUE" if v else "FALSE"
    return str(v)


def desde_celda(v, tipo: str):
    """Valor leido de Sheets (UNFORMATTED_VALUE, fechas como serial) -> tipo Python."""
    if v in (None, ""):
        return None
    if tipo in (E.FECHA, E.FECHA_HORA):
        return desde_serial(v, tipo)
    if tipo == E.ENTERO:
        return int(float(v))
    if tipo == E.NUMERO:
        return float(v)
    if tipo == E.BOOLEANO:
        return v if isinstance(v, bool) else str(v).strip().upper() == "TRUE"
    return str(v)


def filas_desde_valores(tabla: str, valores: list[list]) -> list[dict]:
    if not valores:
        return []
    cab = [str(c) for c in valores[0]]
    esperado = E.columnas(tabla)
    if cab != esperado:
        # Migracion: se acepta un encabezado de una version anterior del esquema si todas sus columnas
        # existen en el esquema actual; las columnas nuevas quedan vacias y se completan al escribir.
        if not (set(cab) <= set(esperado) and len(set(cab)) == len(cab)):
            raise RuntimeError(f"La pestaña {tabla} tiene encabezados distintos al esquema: {cab} != {esperado}")
    ti = E.tipos(tabla)
    filas = [{c: desde_celda(fila[i] if i < len(fila) else None, ti[c]) for i, c in enumerate(cab)}
             for fila in valores[1:] if any(x not in (None, "") for x in fila)]
    return [{c: f.get(c) for c in esperado} for f in filas]


def filas_lb_desde_tabla(filas: Sequence[dict]):
    from .linea_base import FilaLB
    return [FilaLB(**f) for f in filas]


# --- Fusion (idempotente) -----------------------------------------------------------------------

def tipo_de(f: dict) -> str:
    """Filas escritas antes de la fase 3 no tienen tipo_corte: eran oficiales."""
    return f.get("tipo_corte") or E.OFICIAL


def fusionar(tabla: str, existentes: Sequence[dict], nuevas: Sequence[dict], corte: dt.date,
             alcance: set[str] | None = None, tipo_corte: str = E.OFICIAL,
             retencion_preliminar_dias: int = 15) -> list[dict]:
    """Contenido final de una pestaña. alcance = list_ids procesados (None = todos).

    - preliminar: reemplaza las preliminares de su mismo corte, borra las preliminares con corte
      <= corte - retencion (las de los ultimos `retencion` dias se conservan) y no toca las oficiales.
    - oficial: reemplaza las filas oficiales de su corte y borra las preliminares con corte <= su domingo.
    - fotos_tareas solo cambia en corridas oficiales.
    """
    en_alcance = (lambda f: True) if alcance is None else (lambda f: f.get("list_id") in alcance)
    if tabla in E.REEMPLAZO_TOTAL:
        return [f for f in existentes if not en_alcance(f)] + list(nuevas)
    if tabla in E.SOLO_OFICIAL:
        if tipo_corte != E.OFICIAL:
            return list(existentes)
        return [f for f in existentes if not (f.get("corte") == corte and en_alcance(f))] + list(nuevas)
    if tabla in E.POR_CORTE:
        limite = corte - dt.timedelta(days=retencion_preliminar_dias)

        def se_borra(f: dict) -> bool:
            if not en_alcance(f):
                return False
            c = f.get("corte")
            if tipo_de(f) == E.PRELIMINAR:
                if tipo_corte == E.OFICIAL:
                    return c <= corte
                return c == corte or c <= limite
            return tipo_corte == E.OFICIAL and c == corte
        return [f for f in existentes if not se_borra(f)] + list(nuevas)
    if tabla == "linea_base":
        claves = {(f["list_id"], f["rev"]) for f in existentes}
        return list(existentes) + [f for f in nuevas if (f["list_id"], f["rev"]) not in claves]
    if tabla == "ejecuciones":
        return list(existentes) + list(nuevas)
    raise KeyError(tabla)


def completar(tabla: str, filas: Sequence[dict], ident: dict[str, dict]) -> list[dict]:
    """Recalcula es_ultimo_corte en todas las filas. El codigo es la identidad estable de la lista y las
    columnas de presentacion salen de su nombre actual: se actualizan en todas sus filas. jp_* solo se completa
    si falta (filas de una version anterior del esquema), igual que las columnas derivadas de metricas_semanales
    y de advertencias (en filas antiguas el titular y el mensaje salen genericos)."""
    filas = [dict(f) for f in filas]
    if tabla in E.CON_IDENT:
        for f in filas:
            i = ident.get(f.get("list_id"))
            if i is None:
                continue
            if f.get("codigo") is None:
                f.update(i)
            f.update({c: i[c] for c in ("codigo", *(c for c, _ in E.PRESENTACION)) if c in i})
    if tabla == "metricas_semanales":
        for f in filas:
            if f.get("titular") is None:
                f.update(PR.derivadas_semanales(f))
    if tabla == "advertencias":
        for f in filas:
            if f.get("nivel") is None:
                f["nivel"] = PR.nivel(f["tipo"])
            if f.get("mensaje") is None:
                f["mensaje"] = PR.mensaje(f["tipo"])
    if tabla in E.CON_TIPO_CORTE:
        for f in filas:
            f["tipo_corte"] = tipo_de(f)
    if tabla in E.CON_ULTIMO_CORTE and filas:
        # La corrida mas reciente: el corte mayor; a igual corte, la preliminar es posterior a la oficial.
        clave = lambda f: (f["corte"], tipo_de(f) == E.PRELIMINAR)
        ultimo = max(clave(f) for f in filas)
        oficiales = [f["corte"] for f in filas if tipo_de(f) == E.OFICIAL]
        ultimo_oficial = max(oficiales) if oficiales else None
        for f in filas:
            f["es_ultimo_corte"] = clave(f) == ultimo
            f["es_ultimo_oficial"] = tipo_de(f) == E.OFICIAL and f["corte"] == ultimo_oficial
    return filas


def duplicados(tabla: str, filas: Sequence[dict]) -> int:
    """Filas con la misma clave natural (debe ser 0)."""
    claves = [tuple(f.get(c) for c in E.CLAVES[tabla]) for f in filas]
    return len(claves) - len(set(claves))


# --- CSV (dry-run) ------------------------------------------------------------------------------

class AlmacenCsv:
    def __init__(self, directorio: Path):
        self.dir = Path(directorio)

    def escribir(self, tablas: dict[str, Sequence[dict]]) -> list[Path]:
        self.dir.mkdir(parents=True, exist_ok=True)
        out = []
        for tabla, filas in tablas.items():
            ti = E.tipos(tabla)
            p = self.dir / f"{tabla}.csv"
            with p.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(E.columnas(tabla))
                for r in filas:
                    w.writerow([celda_csv(r.get(c), ti[c]) for c in E.columnas(tabla)])
            out.append(p)
        return out

    def agregar_linea_base(self, filas) -> None:
        self.escribir({"linea_base": [f.fila() for f in filas]})

    def leer(self) -> dict[str, list[dict]]:
        """Lee los CSV del directorio (p. ej. un respaldo) con los tipos del esquema."""
        out = {}
        for tabla in E.TABLAS:
            p = self.dir / f"{tabla}.csv"
            if not p.exists():
                continue
            with p.open(encoding="utf-8", newline="") as f:
                filas = list(csv.reader(f))
            out[tabla] = filas_desde_valores(tabla, [filas[0]] + [[_desde_csv(v, t) for v, t in
                                                                   zip(fila, [E.tipos(tabla).get(c) for c in filas[0]])]
                                                                  for fila in filas[1:]]) if filas else []
        return out


def _desde_csv(v: str, tipo: str | None):
    """Texto del CSV -> valor como lo entregaria Sheets (fechas como serial) para reutilizar desde_celda."""
    if v == "" or tipo is None:
        return v
    if tipo == E.FECHA:
        return a_serial(dt.date.fromisoformat(v))
    if tipo == E.FECHA_HORA:
        return a_serial(dt.datetime.strptime(v, "%Y-%m-%d %H:%M:%S"))
    return v


# --- Google Sheets ------------------------------------------------------------------------------

class AlmacenSheets:
    API = "https://sheets.googleapis.com/v4/spreadsheets"

    def __init__(self, spreadsheet_id: str, sesion=None):
        if not spreadsheet_id:
            raise RuntimeError("Falta SHEETS_REPORTES_ID")
        self.id = spreadsheet_id
        self._s = sesion
        self.peticiones: Counter[str] = Counter()
        self._meta: dict | None = None

    @property
    def s(self):
        if self._s is None:
            from .google_auth import sesion
            self._s = sesion(interactivo=False)
        return self._s

    def _req(self, metodo: str, url: str, clave: str, **kw) -> dict:
        self.peticiones[clave] += 1
        r = self.s.request(metodo, url, timeout=120, **kw)
        if r.status_code != 200:
            raise RuntimeError(f"Sheets {r.status_code} en {clave}: {r.text[:500]}")
        return r.json()

    def metadata(self, refrescar: bool = False) -> dict[str, dict]:
        """titulo de pestaña -> properties (sheetId, gridProperties)."""
        if self._meta is None or refrescar:
            d = self._req("GET", f"{self.API}/{self.id}", "leer:metadata",
                          params={"fields": "properties(locale,timeZone),sheets(properties(sheetId,title,gridProperties))"})
            self._meta = {s["properties"]["title"]: s["properties"] for s in d.get("sheets", [])}
            self.locale = d["properties"].get("locale")
            self.zona = d["properties"].get("timeZone")
        return self._meta

    def leer(self, tablas: Iterable[str]) -> dict[str, list[dict]]:
        """Contenido de las pestañas que existen (una sola peticion)."""
        meta = self.metadata()
        existentes = [t for t in tablas if t in meta]
        if not existentes:
            return {}
        d = self._req("GET", f"{self.API}/{self.id}/values:batchGet", "leer:valores",
                      params={"ranges": [f"'{t}'" for t in existentes], "valueRenderOption": "UNFORMATTED_VALUE",
                              "dateTimeRenderOption": "SERIAL_NUMBER", "majorDimension": "ROWS"})
        self._largos = {}
        out = {}
        for t, vr in zip(existentes, d.get("valueRanges", [])):
            valores = vr.get("values", [])
            self._largos[t] = len(valores)
            out[t] = filas_desde_valores(t, valores)
        return out

    def plan(self, finales: dict[str, Sequence[dict]], lb_nuevas: Sequence[dict]) -> dict:
        """Peticiones de escritura que haria `escribir` (para el dry-run y el informe)."""
        meta = self.metadata()
        largos = getattr(self, "_largos", {})
        faltan = [t for t in E.TABLAS if t not in meta]
        tail = [t for t, filas in finales.items() if largos.get(t, 0) > len(filas) + 1]
        celdas = sum((len(f) + 1) * len(E.TABLAS[t]) for t, f in finales.items()) + len(lb_nuevas) * len(E.TABLAS["linea_base"])
        return {"pestañas_nuevas": faltan, "peticiones": 2 + (1 if tail else 0) + 1,
                "detalle": "1 batchUpdate (pestañas, grilla, formatos) + 1 values.batchUpdate + "
                           f"{1 if tail else 0} values.batchClear + 1 lectura de verificación",
                "celdas_escritas": celdas}

    def valores_crudos(self, pestañas: Sequence[str]) -> dict[str, list[list]]:
        """Contenido tal cual de pestañas ajenas al esquema (para respaldarlas y comprobar que estan vacias)."""
        if not pestañas:
            return {}
        d = self._req("GET", f"{self.API}/{self.id}/values:batchGet", "leer:valores",
                      params={"ranges": [f"'{t}'" for t in pestañas], "valueRenderOption": "UNFORMATTED_VALUE"})
        return {t: vr.get("values", []) for t, vr in zip(pestañas, d.get("valueRanges", []))}

    def escribir(self, finales: dict[str, Sequence[dict]], lb_nuevas: Sequence[dict],
                 eliminar: Sequence[str] = ()) -> None:
        """finales: contenido completo de las pestañas que se reescriben; lb_nuevas: filas a agregar a linea_base.
        eliminar: pestañas ajenas al esquema que se borran (el llamador comprueba antes que esten vacias)."""
        meta = self.metadata()
        largos = getattr(self, "_largos", {})
        largo_lb = largos.get("linea_base", 0)
        filas_fin = {t: len(f) + 1 for t, f in finales.items()}
        filas_fin["linea_base"] = max(largo_lb, 1) + len(lb_nuevas)

        reqs = []
        usados = {p["sheetId"] for p in meta.values()}
        ids = {}
        for i, (t, cols) in enumerate(E.TABLAS.items()):
            if t in meta:
                ids[t] = meta[t]["sheetId"]
                gp = meta[t].get("gridProperties", {})
                necesarias = filas_fin.get(t, 1) + 100
                if gp.get("rowCount", 0) < necesarias or gp.get("columnCount", 0) < len(cols):
                    reqs.append({"updateSheetProperties": {"properties": {"sheetId": ids[t], "gridProperties": {
                        "rowCount": max(necesarias, gp.get("rowCount", 0)),
                        "columnCount": max(len(cols), gp.get("columnCount", 0))}},
                        "fields": "gridProperties.rowCount,gridProperties.columnCount"}})
            else:
                ids[t] = next(x for x in range(7_000_000 + i, 8_000_000, 97) if x not in usados)
                usados.add(ids[t])
                reqs.append({"addSheet": {"properties": {"sheetId": ids[t], "title": t, "gridProperties": {
                    "rowCount": max(filas_fin.get(t, 1) + 100, 1000), "columnCount": len(cols)}}}})
            for j, (_, tipo) in enumerate(cols):
                # Formato de fecha en las columnas de fecha; en las demas se quita cualquier formato de
                # numero previo (si las columnas se movieron, un numero no debe quedar con formato de fecha).
                fmt = {"numberFormat": {"type": FORMATO[tipo][0], "pattern": FORMATO[tipo][1]}} if tipo in FORMATO else {}
                reqs.append({"repeatCell": {"range": {"sheetId": ids[t], "startRowIndex": 1, "startColumnIndex": j,
                                                      "endColumnIndex": j + 1},
                                            "cell": {"userEnteredFormat": fmt},
                                            "fields": "userEnteredFormat.numberFormat"}})
        for t in eliminar:
            if t in E.TABLAS:
                raise ValueError(f"No se borra una pestaña del esquema: {t}")
            if t in meta:
                reqs.append({"deleteSheet": {"sheetId": meta[t]["sheetId"]}})
        self._req("POST", f"{self.API}/{self.id}:batchUpdate", "escribir:batchUpdate", json={"requests": reqs})
        if eliminar:
            self.metadata(refrescar=True)

        data = []
        for t, filas in finales.items():
            cols, ti = E.columnas(t), E.tipos(t)
            data.append({"range": f"'{t}'!A1", "values": [cols] + [[celda_sheets(r.get(c), ti[c]) for c in cols] for r in filas]})
        if lb_nuevas:
            cols, ti = E.columnas("linea_base"), E.tipos("linea_base")
            vals = [[celda_sheets(r.get(c), ti[c]) for c in cols] for r in lb_nuevas]
            if largo_lb == 0:
                data.append({"range": "'linea_base'!A1", "values": [cols] + vals})
            else:
                data.append({"range": f"'linea_base'!A{largo_lb + 1}", "values": vals})
        if data:
            self._req("POST", f"{self.API}/{self.id}/values:batchUpdate", "escribir:valores",
                      json={"valueInputOption": "RAW", "data": data})
        sobrantes = [f"'{t}'!A{len(f) + 2}:{_col(len(E.TABLAS[t]))}{largos[t]}"
                     for t, f in finales.items() if largos.get(t, 0) > len(f) + 1]
        if sobrantes:
            self._req("POST", f"{self.API}/{self.id}/values:batchClear", "escribir:limpiar_sobrantes",
                      json={"ranges": sobrantes})

    def agregar_linea_base(self, filas) -> None:
        """Agrega una revision a linea_base (sin tocar las filas existentes)."""
        existentes = {(f["list_id"], f["rev"]) for f in self.leer(["linea_base"]).get("linea_base", [])}
        nuevas = [f.fila() for f in filas if (f.list_id, f.rev) not in existentes]
        if not nuevas:
            raise RuntimeError("Esa revisión ya existe en linea_base; no se escribe nada")
        self.escribir({}, nuevas)
        problemas, _ = self.verificar_tipos(["linea_base"])
        if problemas:
            raise RuntimeError("Tipos no reconocidos por Sheets: " + "; ".join(problemas))

    def verificar_tipos(self, tablas: Iterable[str], filas: int = 50) -> tuple[list[str], dict[str, dict[str, str]]]:
        """Lee las primeras `filas` filas de datos de cada pestaña (effectiveValue y effectiveFormat) y confirma
        que Sheets guarda los numeros como numero y las fechas como numero con formato de fecha.

        Devuelve (problemas, detalle): detalle[tabla][columna] = "numero" / "fecha" / "fecha_hora" / "texto" /
        "sin datos" segun lo que se verifico.
        """
        tablas = [t for t in tablas]
        d = self._req("GET", f"{self.API}/{self.id}", "leer:verificacion",
                      params={"ranges": [f"'{t}'!A2:{_col(len(E.TABLAS[t]))}{filas + 1}" for t in tablas],
                              "fields": "sheets(properties(title),data(rowData(values(effectiveValue,effectiveFormat(numberFormat)))))"})
        problemas: list[str] = []
        detalle: dict[str, dict[str, str]] = {}
        for sh in d.get("sheets", []):
            t = sh["properties"]["title"]
            if t not in E.TABLAS:
                continue
            det = {c: "sin datos" for c, _ in E.TABLAS[t]}
            for fila in (sh.get("data") or [{}])[0].get("rowData") or []:
                for (col, tipo), celda in zip(E.TABLAS[t], fila.get("values", [])):
                    ev = celda.get("effectiveValue") or {}
                    if not ev:
                        continue
                    nf = (celda.get("effectiveFormat") or {}).get("numberFormat", {}).get("type")
                    if tipo in (E.NUMERO, E.ENTERO):
                        ok = "numberValue" in ev and nf not in ("DATE", "DATE_TIME")
                    elif tipo == E.BOOLEANO:
                        ok = "boolValue" in ev
                    elif tipo in FORMATO:
                        ok = "numberValue" in ev and nf == FORMATO[tipo][0]
                    else:
                        ok = "stringValue" in ev or "numberValue" not in ev
                    if not ok:
                        problemas.append(f"{t}.{col}: esperado {tipo}, Sheets tiene {ev} con formato {nf}")
                    elif det[col] == "sin datos":
                        det[col] = {E.NUMERO: "numero", E.ENTERO: "numero", E.FECHA: f"fecha ({nf})",
                                    E.FECHA_HORA: f"fecha_hora ({nf})", E.BOOLEANO: "booleano"}.get(tipo, "texto")
            detalle[t] = det
        return problemas, detalle


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s
