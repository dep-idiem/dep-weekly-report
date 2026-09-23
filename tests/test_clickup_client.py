import time

import pytest

from dep_clickup.client import ClickUpClient, ClickUpError


class Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers, self.text = status, body or {}, headers or {}, str(body)

    def json(self):
        return self._body


class Sesion:
    """Sesion falsa: solo tiene get(); si el cliente intentara post/put/delete fallaria."""
    def __init__(self, respuestas):
        self.respuestas, self.headers, self.llamadas = list(respuestas), {}, []

    def get(self, url, params=None, timeout=None):
        self.llamadas.append(url)
        return self.respuestas.pop(0)


def cliente(respuestas, **kw):
    esperas = []
    c = ClickUpClient("tk", session=Sesion(respuestas), sleep=esperas.append, **kw)
    return c, esperas


def test_429_espera_hasta_reset_y_reintenta():
    c, esperas = cliente([Resp(429, headers={"X-RateLimit-Reset": str(time.time() + 5)}), Resp(200, {"ok": 1})])
    assert c.get("/team") == {"ok": 1}
    assert c.request_count == 2
    assert 4 <= esperas[0] <= 7


def test_error_4xx_no_reintenta():
    c, _ = cliente([Resp(401, {"err": "Token invalid"})])
    with pytest.raises(ClickUpError) as e:
        c.get("/team")
    assert e.value.status == 401


def test_limite_local_por_minuto():
    t = [0.0]
    esperas = []
    c = ClickUpClient("tk", session=Sesion([Resp(200)] * 3), sleep=lambda s: (esperas.append(s), t.__setitem__(0, t[0] + s)),
                      clock=lambda: t[0], max_per_min=2)
    for _ in range(3):
        c.get("/team")
    assert len(esperas) == 1 and esperas[0] > 59


def test_paginacion_de_tareas():
    c, _ = cliente([Resp(200, {"tasks": [{"id": "a"}], "last_page": False}),
                    Resp(200, {"tasks": [{"id": "b"}], "last_page": True})])
    assert [t["id"] for t in c.list_tasks_raw("901328186343")] == ["a", "b"]
    assert c.request_log["/list/{id}/task"] == 2


def test_solo_un_filtro_de_ubicacion():
    c, _ = cliente([])
    with pytest.raises(ValueError):
        c.list_time_entries(None, None, list_id="1", folder_id="2", assignees=[1], team_id="t")
