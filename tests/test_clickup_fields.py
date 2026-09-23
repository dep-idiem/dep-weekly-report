import datetime as dt

from dep_clickup.fields import progress_fraction, resolve_custom_fields

DROPDOWN_TC = {"options": [
    {"id": "f0baab6c", "name": "-", "orderindex": 0},
    {"id": "b0cbf5fc", "name": "2026.0195 Otro", "orderindex": 1},
    {"id": "c1c1c1c1", "name": "2026.0152 Evaluación Estructural", "orderindex": 4},
]}


def campo(name, type_, value, tc=None):
    f = {"id": name, "name": name, "type": type_, "type_config": tc or {}}
    if value is not None:
        f["value"] = value
    return f


def test_resolucion_por_nombre_y_vacios():
    r = resolve_custom_fields([campo("HH Presupuestadas", "number", "36"), campo("Cliente", "short_text", None)])
    assert r["HH Presupuestadas"].value == 36.0
    assert r["HH Presupuestadas"].raw == "36"
    assert r["Cliente"].value is None


def test_dropdown_por_orderindex_y_por_id():
    r = resolve_custom_fields([campo("Proyecto v0.1", "drop_down", "4", DROPDOWN_TC),
                               campo("Otro", "drop_down", 1, DROPDOWN_TC),
                               campo("PorId", "drop_down", "b0cbf5fc", DROPDOWN_TC),
                               campo("Cero", "drop_down", 0, DROPDOWN_TC)])
    assert r["Proyecto v0.1"].value == "2026.0152 Evaluación Estructural"
    assert r["Otro"].value == "2026.0195 Otro"
    assert r["PorId"].value == "2026.0195 Otro"
    assert r["Cero"].value == "-"


def test_labels():
    tc = {"options": [{"id": "a", "label": "Uno"}, {"id": "b", "label": "Dos"}]}
    assert resolve_custom_fields([campo("L", "labels", ["b", "a"], tc)])["L"].value == ["Dos", "Uno"]


def test_fecha():
    v = resolve_custom_fields([campo("Fecha Entrega Contractual", "date", "1790924400000")])["Fecha Entrega Contractual"].value
    assert v.date() == dt.date(2026, 10, 2)
    assert v.utcoffset() == dt.timedelta(hours=-3)


def test_manual_progress_formato_real_de_la_api():
    tc = {"end": 100, "start": 0}
    # Valores observados en la lista 901328186343 (2026-09-23)
    assert progress_fraction({"current": "100", "percent_completed": 1}, tc) == 1.0
    assert progress_fraction({"current": 0, "percent_completed": 0}, tc) == 0.0
    assert progress_fraction({"current": "57", "percent_completed": 0.57}, tc) == 0.57
    r = resolve_custom_fields([campo("Avance Real", "manual_progress", {"current": "100", "percent_completed": 1}, tc)])
    assert r["Avance Real"].value == 1.0


def test_manual_progress_otra_escala_y_sin_current():
    assert progress_fraction({"current": 5}, {"start": 0, "end": 10}) == 0.5
    assert progress_fraction({"percent_completed": 0.25}, {}) == 0.25
    assert progress_fraction(None) is None


def test_users_y_checkbox():
    r = resolve_custom_fields([campo("JP Responsable", "users", [{"id": 1, "username": "Ana"}]),
                               campo("Entregable", "checkbox", "true")])
    assert r["JP Responsable"].value == ["Ana"]
    assert r["Entregable"].value is True
