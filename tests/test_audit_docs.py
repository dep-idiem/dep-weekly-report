from audit_docs.drive import id_desde_url
from audit_docs.reglas import Reglas, buscar_subcarpeta, extension


def test_id_desde_url():
    assert id_desde_url("https://drive.google.com/drive/folders/1OFtr9deTIyc0gDdb9cv9KFNTfjXetM7k?usp=sharing") == \
        "1OFtr9deTIyc0gDdb9cv9KFNTfjXetM7k"
    assert id_desde_url("https://drive.google.com/open?id=1Ph2FTKZR30Gy2oTVjLh") == "1Ph2FTKZR30Gy2oTVjLh"
    assert id_desde_url("") is None and id_desde_url("sin link") is None


def _c(*nombres):
    return [{"id": str(i), "name": n} for i, n in enumerate(nombres)]


def test_buscar_subcarpeta_modos():
    e = "03 Propuesta tecnica y economica"
    assert buscar_subcarpeta(e, _c(e))[1] == "exacto"
    assert buscar_subcarpeta(e, _c("03 Propuesta Técnica y Económica"))[1] == "normalizado"
    assert buscar_subcarpeta(e, _c("03 Propuesta tecnica y ecnonomica"))[1] == "variante"
    assert buscar_subcarpeta(e, _c("03_Propuesta tecnica economica"))[1] == "aproximado"
    assert buscar_subcarpeta(e, _c("01 Antecedentes", "03 Oferta"))[1] == "por_numero"
    assert buscar_subcarpeta(e, _c("01 Antecedentes", "04 Oferta enviada")) == (None, None)
    assert buscar_subcarpeta("04 Oferta enviada", _c("4. Oferta Enviada"))[1] == "normalizado"


def test_extension():
    assert extension("Oferta.PDF") == ".pdf"
    assert extension("sin punto") == "(sin extensión)"
    assert extension("Doc", "application/vnd.google-apps.document") == "(gdoc)"


def test_reglas_aplicables():
    r = Reglas.cargar()
    ids = lambda est: [x.id for x in r.aplicables(est)]  # noqa: E731
    assert ids("enviada") == ["propuesta_economica", "propuesta_tecnica", "oferta_enviada"]
    assert ids("perdida") == ids("enviada") == ids("cerrada")   # perdida hereda; cerrada -> GANADA
    assert ids("en elaboración") == []                          # reglas de 03 desde ENVIADA
    assert ids("intake") == ids("cancelada") == []              # sin reglas
    assert r.estado_conocido("cancelada") and not r.estado_conocido("pausada")


def test_regla_codigo_revisar():
    from audit_docs.reglas import Regla, codigo_archivo
    assert codigo_archivo("PR.DEP.2026-0262 Evaluación.docx") == "2026.0262"
    tec = next(x for x in Reglas.cargar().reglas if x.id == "propuesta_tecnica")
    ev = tec.evaluar([{"name": "PR.DEP.2026.0249 Oferta.pdf"}, {"name": "PR.DEP.2024.0063 Incendio.docx"},
                      {"name": "Correo de IDIEM - Fwd.pdf"}, {"name": "PR.DGI.2026.107 EMS.pdf"}], "2026.0249")
    assert ev["coincidencias"] == ["PR.DEP.2026.0249 Oferta.pdf"]
    assert ev["otro_codigo"] == ["PR.DEP.2024.0063 Incendio.docx"]
    of = Regla("o", "", "oferta_enviada", r"\.pdf$", "ENVIADA", patron_revisar=r"\.(zip|rar)$")
    assert of.evaluar([{"name": "3. Final.rar"}])["por_revisar"] == ["3. Final.rar"]
    assert of.evaluar([{"name": "a.pdf"}, {"name": "b.zip"}])["por_revisar"] == []


def test_coincidencias():
    regla = Reglas.cargar().reglas[0]
    assert regla.coincidencias([{"name": "PE.XLSX"}, {"name": "a.pdf"}, {"name": "b.xls"}]) == ["PE.XLSX", "b.xls"]


def _fila(**kw):
    from audit_docs.recon import Fila
    base = dict(task_id="t", ss_code="2026.0001", codigo="2026.0001", nombre="n", estado="enviada", estado_pipeline=None,
                tipo_dep="Ingeniería", jp="", fecha_creada=None, fecha_estado=None, fecha_fuente="", link_pr=None, link_pj=None)
    base.update(kw)
    return Fila(**base)


DEP = "DEP - CENTRAL / 01 Propuestas / 2026"


def _subs(a03, a04):
    from audit_docs.recon import Sub
    return {"tecnica_economica": Sub("tecnica_economica", "03", carpeta={"id": "a", "name": "03"}, archivos=a03),
            "oferta_enviada": Sub("oferta_enviada", "04", carpeta={"id": "b", "name": "04"}, archivos=a04)}


def test_clasificar_orden_de_decision():
    import datetime as dt
    from audit_docs.recon import _clasificar
    r = Reglas.cargar()
    f = _fila(tipo_dep="Laboratorio"); _clasificar(f, r); assert f.resultado == "FUERA_DE_ALCANCE"
    f = _fila(); _clasificar(f, r); assert f.resultado == "SIN_CARPETA"
    f = _fila(codigo="2025.0311"); _clasificar(f, r); assert f.resultado == "HISTORICA"   # codigo_inicio_make
    r.fecha_inicio_make = dt.date(2026, 3, 1)
    f = _fila(fecha_creada=dt.datetime(2026, 2, 1)); _clasificar(f, r); assert f.resultado == "HISTORICA"
    f = _fila(link_pr="x", carpeta_encontrada="si", ubicacion="see-lab / [WIP] Propuestas"); _clasificar(f, r)
    assert f.resultado == "FUERA_DE_ALCANCE"
    f = _fila(link_pr="x", carpeta_encontrada="si", ubicacion=DEP, estado="cancelada")
    _clasificar(f, r); assert f.resultado == "NO_APLICA"


def test_clasificar_economica_y_causa_oferta():
    from audit_docs.recon import _clasificar
    r = Reglas.cargar()
    tec, eco = {"name": "PR.DEP.2026.0001 Oferta.pdf"}, {"name": "Planilla PR.DEP.2026-0001.xlsx"}
    # Económica: faltante y con el código de la tarea (un Excel con otro código no sirve).
    f = _fila(link_pr="x", carpeta_encontrada="si", ubicacion=DEP, subs=_subs([tec, {"name": "Planilla 2025.0165.xlsx"}], []))
    _clasificar(f, r)
    e = {x["regla"].id: x for x in f.evaluacion}
    assert f.resultado == "INCOMPLETO" and not e["propuesta_economica"]["cumple"]
    # 04 vacía y PDF con el código en 03: oferta_mal_ubicada.
    assert e["oferta_enviada"]["causa"] == "oferta_mal_ubicada" == f.causa_oferta
    assert e["oferta_enviada"]["pista"] == ["PR.DEP.2026.0001 Oferta.pdf"]
    # Sin PDF con el código en ninguna parte: sin_oferta.
    f = _fila(link_pr="x", carpeta_encontrada="si", ubicacion=DEP, subs=_subs([{"name": "PR.DEP.2026.0001 a.docx"}, eco], []))
    _clasificar(f, r)
    assert f.causa_oferta == "sin_oferta" and f.resultado == "INCOMPLETO"
    # Oferta en 04 solo como .rar: no cumple, causa oferta_comprimida (INCOMPLETO, igual que en ClickUp).
    f = _fila(link_pr="x", carpeta_encontrada="si", ubicacion=DEP, subs=_subs([tec, eco], [{"name": "Final.rar"}]))
    _clasificar(f, r)
    assert f.resultado == "INCOMPLETO" and f.causa_oferta == "oferta_comprimida"
    assert any("solo comprimidos" in o for o in f.observaciones)
    # Con el PDF suelto además del .rar: cumple.
    f = _fila(link_pr="x", carpeta_encontrada="si", ubicacion=DEP, subs=_subs([tec, eco], [{"name": "Final.rar"}, {"name": "Oferta.pdf"}]))
    _clasificar(f, r)
    assert f.resultado == "COMPLETO" and f.causa_oferta == ""


def test_leer_un_nivel_ignorando_old():
    from audit_docs.drive import FOLDER
    from audit_docs.recon import Sub, _leer

    class DR:
        arbol = {"03": [{"id": "r1", "name": "Rev 1", "mimeType": FOLDER}, {"id": "old", "name": "OLD", "mimeType": FOLDER},
                        {"id": "f", "name": "a.docx", "mimeType": "x"}],
                 "r1": [{"id": "g", "name": "b.pdf", "mimeType": "x"}, {"id": "r2", "name": "Sub", "mimeType": FOLDER}],
                 "old": [{"id": "h", "name": "viejo.pdf", "mimeType": "x"}]}

        def hijos(self, fid):
            return self.arbol.get(fid, [])

    s = Sub("tecnica_economica", "03")
    _leer(s, DR(), Reglas.cargar(), "03", "", 1)
    assert [a["name"] for a in s.archivos] == ["b.pdf", "a.docx"]
    assert s.ignoradas == ["OLD"] and s.subcarpetas == ["Rev 1", "Rev 1/Sub (no leída)"]


class _CUFalso:
    """Cliente de escritura falso: guarda el valor del campo por tarea y registra las llamadas."""

    def __init__(self, valores):
        self.valores, self.llamadas = dict(valores), []

    def get(self, path, params=None):
        tid = path.rsplit("/", 1)[1]
        return {"custom_fields": [{"id": "F", "value": self.valores.get(tid)}]}

    def set_campo(self, tid, fid, valor):
        self.llamadas.append(("set", tid, valor)); self.valores[tid] = valor; return 200

    def borrar_campo(self, tid, fid):
        self.llamadas.append(("del", tid)); self.valores[tid] = None; return 200


def test_fix_links_apply_respalda_y_revert(tmp_path):
    import csv
    from audit_docs.fix_links import COLUMNAS, aplicar, revertir
    entrada = tmp_path / "fix_links_2026-10-06.csv"
    filas = [dict(task_id="t1", ss_code="2026.0304", estado="intake", campo="Drive PR URL", field_id="F",
                  valor_actual="L-backup", valor_nuevo="L-pr", motivo="A1", carpeta="PR", ubicacion="DEP"),
             dict(task_id="t2", ss_code="2026.0278", estado="intake", campo="Drive PR URL", field_id="F",
                  valor_actual="L-viejo", valor_nuevo="L-pr2", motivo="A1", carpeta="PR", ubicacion="DEP"),
             dict(task_id="t3", ss_code="2026.0150", estado="enviada", campo="Drive PR URL", field_id="F",
                  valor_actual="", valor_nuevo="L-pr3", motivo="A3", carpeta="PR", ubicacion="DEP")]
    with entrada.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNAS); w.writeheader(); w.writerows(filas)
    # t2 cambió a mano desde el dry-run: no se escribe. A3 no está autorizado: no se toca.
    cu = _CUFalso({"t1": "L-backup", "t2": "otro", "t3": None})
    assert aplicar(cu, entrada, {"A1"}, None, "ahora") == 0
    assert cu.llamadas == [("set", "t1", "L-pr")]
    backup = tmp_path / "fix_links_2026-10-06_backup.csv"
    assert [r["valor_anterior"] for r in csv.DictReader(backup.open(encoding="utf-8-sig"))] == ["L-backup", "otro"]
    # Reaplicar no vuelve a escribir (el valor vivo ya no es el del dry-run).
    cu.llamadas.clear(); aplicar(cu, entrada, {"A1"}, None, "ahora"); assert cu.llamadas == []
    # Revert de una sola tarea: vuelve al primer valor respaldado.
    revertir(cu, backup, {"2026.0304"}, "ahora")
    assert cu.valores["t1"] == "L-backup" and cu.llamadas == [("set", "t1", "L-backup")]


def test_codigo_plantilla_y_pistas():
    from audit_docs.reglas import codigo_archivo, pista_codigo
    assert codigo_archivo("Planilla Base PR DEP 2026 - 0221.xlsx") == "2026.0221"
    assert codigo_archivo("PR.DEP.2026 0152.xlsx") == codigo_archivo("PR_DEP_2026_0152.xls") == "2026.0152"
    eco, tec = Reglas.cargar().reglas[0], Reglas.cargar().reglas[1]
    assert eco.evaluar([{"name": "Planilla Base PR DEP 2026 - 0221.xlsx"}], "2026.0221")["coincidencias"]
    assert eco.evaluar([{"name": "PR.DEP.2025.0000 ECO (uso público) v.0.xlsx"}], "2026.0177")["pista_codigo"] == "sin_codigo"
    assert eco.evaluar([{"name": "Planilla Base PR DEP 2026.xlsx"}], "2026.0153")["pista_codigo"] == "sin_codigo"
    # Año equivocado: la misma pista en la económica y en la técnica.
    archivos = [{"name": "PR.DEP.2025.0171 GDS.xlsx"}, {"name": "PR.DEP.2025.0171 - Evaluacion.docx"}]
    assert eco.evaluar(archivos, "2026.0171")["pista_codigo"] == tec.evaluar(archivos, "2026.0171")["pista_codigo"] == "otro_anio"
    assert eco.evaluar([], "2026.0171")["pista_codigo"] == "" and pista_codigo([], "2026.0171") == ""


# --- Fase 2, bloque B: checklist y Docs OK ---------------------------------------------------

class _CUChecklist:
    """ClickUp falso con checklists y un campo Docs OK, para probar el plan contra un estado."""

    def __init__(self, tarea):
        self.tarea, self.n, self.escrituras = tarea, 0, 0

    def _id(self):
        self.n += 1; return f"id{self.n}"

    def crear_checklist(self, tid, nombre):
        self.escrituras += 1
        ch = {"id": self._id(), "name": nombre, "items": []}; self.tarea["checklists"].append(ch); return ch

    def _ch(self, cid):
        return next(c for c in self.tarea["checklists"] if c["id"] == cid)

    def crear_item(self, cid, nombre):
        self.escrituras += 1
        ch = self._ch(cid); ch["items"].append({"id": self._id(), "name": nombre, "resolved": False}); return ch

    def editar_item(self, cid, iid, **cambios):
        self.escrituras += 1
        ch = self._ch(cid); next(i for i in ch["items"] if i["id"] == iid).update(cambios); return ch

    def set_campo(self, tid, fid, valor):
        self.escrituras += 1; self.tarea["docs"] = valor; return 200

    def borrar_campo(self, tid, fid):
        self.escrituras += 1; self.tarea["docs"] = None; return 200


OPC = {"Completo": "o1", "Incompleto": "o2", "Sin carpeta": "o3"}


def _ev(resultado="INCOMPLETO", **por_regla):
    from audit_docs.sync_checklists import Evaluacion
    base = {"propuesta_economica": dict(cumple=True), "propuesta_tecnica": dict(cumple=True),
            "oferta_enviada": dict(cumple=False, causa="oferta_mal_ubicada")}
    base.update(por_regla)
    ev = Evaluacion("t", "2026.0152", "n", "ganada", "JP", resultado, "c")
    ev.reglas = [{"id": k, "aplica": True, "cumple": v.get("cumple", True), "causa": v.get("causa", ""),
                  "pista_codigo": v.get("pista_codigo", "")} for k, v in base.items()]
    return ev


def _docs(tarea):
    return {v: k for k, v in OPC.items()}.get(tarea["docs"])


def test_checklist_idempotente_y_texto_mal_ubicada():
    from audit_docs.sync_checklists import aplicar_plan, planificar
    r = Reglas.cargar()
    tarea = {"checklists": [], "docs": None}
    cu = _CUChecklist(tarea)
    p = planificar(_ev(), tarea, r, _docs(tarea))
    assert p.crear_checklist and [i["accion"] for i in p.items] == ["crear"] * 3
    aplicar_plan(cu, p, "F", OPC, lambda *a: None)
    ch = tarea["checklists"][0]
    assert ch["name"] == "Documentos" and _docs(tarea) == "Incompleto"
    nombres = {i["name"]: i["resolved"] for i in ch["items"]}
    assert nombres["[oferta] Oferta enviada en 04 — hay un PDF con el código en 03: mover a 04"] is False
    assert nombres[next(n for n in nombres if n.startswith("[tecnica]"))] is True
    # Segunda corrida igual: nada que escribir.
    antes = cu.escrituras
    p2 = planificar(_ev(), tarea, r, _docs(tarea))
    assert p2.escrituras == 0 and not p2.crear_checklist
    aplicar_plan(cu, p2, "F", OPC, lambda *a: None)
    assert cu.escrituras == antes and len(tarea["checklists"]) == 1


def test_checklist_gobernada_por_el_worker_respeta_items_propios():
    from audit_docs.sync_checklists import aplicar_plan, planificar
    r = Reglas.cargar()
    tarea = {"checklists": [], "docs": None}
    cu = _CUChecklist(tarea)
    aplicar_plan(cu, planificar(_ev(), tarea, r, None), "F", OPC, lambda *a: None)
    ch = tarea["checklists"][0]
    of = next(i for i in ch["items"] if i["name"].startswith("[oferta]"))
    of["resolved"] = True                                            # alguien la marcó a mano
    ch["items"].append({"id": "propio", "name": "Pedir firma al cliente", "resolved": False})
    p = planificar(_ev(), tarea, r, _docs(tarea))
    assert [i["accion"] for i in p.items].count("editar") == 1
    aplicar_plan(cu, p, "F", OPC, lambda *a: None)
    assert of["resolved"] is False                                   # el archivo no está: se desmarca
    assert {"id": "propio", "name": "Pedir firma al cliente", "resolved": False} in ch["items"]
    # Se sube la oferta a 04: el ítem cambia de texto y queda resuelto; Docs OK pasa a Completo.
    p = planificar(_ev("COMPLETO", oferta_enviada=dict(cumple=True)), tarea, r, _docs(tarea))
    aplicar_plan(cu, p, "F", OPC, lambda *a: None)
    assert of["resolved"] is True and of["name"] == "[oferta] Oferta enviada (PDF final o firmado)"
    assert _docs(tarea) == "Completo"


def test_no_aplica_limpia_docs_ok_y_no_toca_checklist():
    from audit_docs.sync_checklists import aplicar_plan, planificar
    r = Reglas.cargar()
    tarea = {"checklists": [{"id": "c", "name": "Documentos", "items": []}], "docs": "o2"}
    cu = _CUChecklist(tarea)
    for resultado in ("NO_APLICA", "HISTORICA", "FUERA_DE_ALCANCE"):
        tarea["docs"] = "o2"
        p = planificar(_ev(resultado), tarea, r, _docs(tarea))
        assert p.docs_ok_nuevo is None and p.items == [] and not p.crear_checklist
        aplicar_plan(cu, p, "F", OPC, lambda *a: None)
        assert tarea["docs"] is None
    # Sin carpeta: campo "Sin carpeta" y sin checklist.
    p = planificar(_ev("SIN_CARPETA"), tarea, r, None)
    assert p.docs_ok_nuevo == "Sin carpeta" and p.items == []


def test_texto_item_comprimido_y_pistas_de_codigo():
    from audit_docs.sync_checklists import items_deseados
    r = Reglas.cargar()
    ev = _ev(oferta_enviada=dict(cumple=False, causa="oferta_comprimida"),
             propuesta_economica=dict(cumple=False, pista_codigo="sin_codigo"),
             propuesta_tecnica=dict(cumple=False, pista_codigo="otro_anio"))
    t = {i["etiqueta"]: i["nombre"] for i in items_deseados(ev, r)}
    assert t["oferta"] == "[oferta] Oferta enviada en 04 — hay un .zip en 04: subir el PDF de lo enviado por separado"
    assert t["economica"] == "[economica] Propuesta económica — hay un Excel sin código en 03: renombrar o reemplazar"
    assert t["tecnica"].endswith("otro año: renombrar")
