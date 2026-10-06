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


def test_clasificar_niveles_y_pista():
    from audit_docs.recon import _clasificar
    r = Reglas.cargar()
    tec = {"name": "PR.DEP.2026.0001 Oferta.pdf"}
    # Sin Excel (advertencia) y con 04 vacío pero la oferta en 03: INCOMPLETO solo por oferta_enviada, con pista.
    f = _fila(link_pr="x", carpeta_encontrada="si", ubicacion=DEP, subs=_subs([tec], []))
    _clasificar(f, r)
    assert f.resultado == "INCOMPLETO"
    e = {x["regla"].id: x for x in f.evaluacion}
    assert not e["propuesta_economica"]["cumple"] and e["propuesta_economica"]["nivel"] == "advertencia"
    assert e["oferta_enviada"]["pista"] == ["PR.DEP.2026.0001 Oferta.pdf"]
    # Con la oferta en 04 (aunque sea .rar): COMPLETO pese a la advertencia.
    f = _fila(link_pr="x", carpeta_encontrada="si", ubicacion=DEP, subs=_subs([tec], [{"name": "Final.rar"}]))
    _clasificar(f, r)
    assert f.resultado == "COMPLETO" and any("por revisar" in o for o in f.observaciones)


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
