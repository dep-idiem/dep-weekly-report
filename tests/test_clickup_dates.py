import datetime as dt

from dep_clickup.client import parse_task, parse_time_entry
from dep_clickup.config import TZ
from dep_clickup.dates import local_day_bounds_ms, ms_to_local, ms_to_local_date


def ms(y, mo, d, h=0, mi=0, tz=dt.timezone.utc):
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=tz).timestamp() * 1000)


def test_vacios():
    assert ms_to_local(None) is None
    assert ms_to_local("") is None
    assert ms_to_local_date(None) is None


def test_invierno_utc_menos_4():
    # 2026-08-24T08:51:26.145-04:00 (fila 3 de 'Horas Cargadas')
    t = ms_to_local(1787575886145)
    assert t.utcoffset() == dt.timedelta(hours=-4)
    assert (t.date(), t.hour, t.minute) == (dt.date(2026, 8, 24), 8, 51)


def test_verano_utc_menos_3():
    # Chile pasa a -03 el primer domingo de septiembre (2026-09-06)
    t = ms_to_local(ms(2026, 9, 10, 15))
    assert t.utcoffset() == dt.timedelta(hours=-3)
    assert t.hour == 12


def test_fecha_local_cerca_de_medianoche():
    # 02:30 UTC del 25-08 es 22:30 del 24-08 en Santiago: la entrada es del 24.
    assert ms_to_local_date(ms(2026, 8, 25, 2, 30)) == dt.date(2026, 8, 24)
    # 01:37 hora local del 24-08 (fila 4 del Excel) sigue siendo 24-08
    assert ms_to_local_date(1787549873824) == dt.date(2026, 8, 24)


def test_due_date_de_clickup_es_4am_local():
    # ClickUp guarda fechas sin hora a las 04:00 locales: 1787558400000 = 2026-08-24T04:00-04:00
    assert ms_to_local_date("1787558400000") == dt.date(2026, 8, 24)


def test_cambio_de_hora_limites_del_dia():
    # 2026-09-06 dura 23 h en Santiago: el reloj salta de 00:00 a 01:00, el dia empieza a la 01:00.
    t0, t1 = local_day_bounds_ms(dt.date(2026, 9, 6), dt.date(2026, 9, 6))
    assert (t1 + 1 - t0) == 23 * 3600 * 1000
    assert ms_to_local(t0) == dt.datetime(2026, 9, 6, 1, 0, tzinfo=TZ)
    assert ms_to_local_date(t0 - 1) == dt.date(2026, 9, 5)


def test_limites_incluyen_ambos_extremos():
    t0, t1 = local_day_bounds_ms(dt.date(2026, 8, 24), dt.date(2026, 8, 25))
    assert ms_to_local_date(t0) == dt.date(2026, 8, 24)
    assert ms_to_local_date(t1) == dt.date(2026, 8, 25)
    assert ms_to_local_date(t1 + 1) == dt.date(2026, 8, 26)


def test_parse_time_entry_fecha_local_y_horas():
    e = parse_time_entry({"id": "1", "user": {"id": 5, "username": "x"}, "task": {"id": "t", "name": "T"},
                          "task_location": {"list_id": "L"}, "start": str(ms(2026, 8, 25, 2, 30)),
                          "end": str(ms(2026, 8, 25, 4)), "duration": "5400000", "at": "1787607566145"})
    assert e.date == dt.date(2026, 8, 24)
    assert e.hours == 1.5
    assert e.list_id == "L"


def test_parse_time_entry_cronometro_corriendo():
    assert parse_time_entry({"id": "1", "user": {"id": 5}, "start": "1", "duration": "-1"}) is None


def test_parse_task_fechas():
    t = parse_task({"id": "a", "name": "n", "status": {"status": "to do"}, "start_date": "1787558400000",
                    "due_date": "1787817600000", "time_estimate": 129600000, "assignees": [], "custom_fields": []})
    assert (t.start_date, t.due_date) == (dt.date(2026, 8, 24), dt.date(2026, 8, 27))
    assert t.time_estimate_h == 36
