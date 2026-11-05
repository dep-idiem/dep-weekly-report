"""Drive del informe semanal: lee la planilla de ausencias y publica los HTML.

En GitHub Actions basta GOOGLE_REFRESH_TOKEN_DRIVE_RW (con GOOGLE_OAUTH_CLIENT_JSON), que sirve para leer y para
escribir. En local lee con secrets/google_token_drive.json y escribe con secrets/google_token_drive_rw.json.
Nunca abre el navegador ni imprime secretos.
"""
from __future__ import annotations

import json
import os

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

from audit_docs.drive import API, FOLDER, DriveClient
from audit_docs.drive import cargar_credenciales as credenciales_lectura
from dep_clickup.config import ROOT
from dep_reportes.google_auth import TOKEN_URI, _cliente

SCOPES_RW = ["https://www.googleapis.com/auth/drive"]
TOKEN_RW_JSON = ROOT / "secrets" / "google_token_drive_rw.json"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
ENLACE_ARCHIVO = "https://drive.google.com/file/d/{}/view"
ENLACE_CARPETA = "https://drive.google.com/drive/folders/{}"


def _credenciales(escritura: bool) -> Credentials:
    refresh = os.getenv("GOOGLE_REFRESH_TOKEN_DRIVE_RW")
    if refresh and os.getenv("GOOGLE_OAUTH_CLIENT_JSON"):
        c = _cliente(json.loads(os.environ["GOOGLE_OAUTH_CLIENT_JSON"]))
        return Credentials(None, refresh_token=refresh, token_uri=c.get("token_uri", TOKEN_URI),
                           client_id=c["client_id"], client_secret=c["client_secret"], scopes=SCOPES_RW)
    if not escritura:
        return credenciales_lectura(interactivo=False)
    if not TOKEN_RW_JSON.exists():
        raise RuntimeError("Sin credenciales de escritura en Drive: falta el secreto GOOGLE_REFRESH_TOKEN_DRIVE_RW "
                           f"(en local, {TOKEN_RW_JSON.name})")
    creds = Credentials.from_authorized_user_file(str(TOKEN_RW_JSON), SCOPES_RW)
    if not creds.valid:
        creds.refresh(Request())
    return creds


def cliente(escritura: bool = False) -> DriveClient:
    return DriveClient(AuthorizedSession(_credenciales(escritura)))


def _comprobar(r, que: str) -> dict:
    if r.status_code != 200:
        raise RuntimeError(f"Drive {r.status_code} al {que}: {r.text[:300]}")
    return r.json()


def publicar(archivos: dict[str, bytes], destino: dict[str, str], carpeta_id: str,
             dr: DriveClient | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Sube cada archivo a <carpeta_id>/<destino[archivo]>/, creando la carpeta si falta. Devuelve los enlaces
    (carpeta → enlace, archivo → enlace). Si el archivo ya existe se reemplaza: repetir la corrida no duplica."""
    dr = dr or cliente(escritura=True)
    carpetas = {h["name"].strip(): h["id"] for h in dr.hijos(carpeta_id) if h.get("mimeType") == FOLDER}
    enlaces_archivos: dict[str, str] = {}
    usadas: dict[str, str] = {}
    for nombre, contenido in archivos.items():
        carpeta = destino[nombre]
        nueva = carpeta not in carpetas
        if nueva:
            carpetas[carpeta] = _comprobar(
                dr.s.post(f"{API}/files", params={"supportsAllDrives": "true", "fields": "id,name"},
                          json={"name": carpeta, "mimeType": FOLDER, "parents": [carpeta_id]}, timeout=60),
                f"crear la carpeta «{carpeta}»")["id"]
        padre = carpetas[carpeta]
        usadas[carpeta] = ENLACE_CARPETA.format(padre)
        existentes = {} if nueva else {h["name"]: h["id"] for h in dr.hijos(padre)}
        if nombre in existentes:
            fid = existentes[nombre]
            _comprobar(dr.s.patch(f"{UPLOAD}/{fid}", params={"uploadType": "media", "supportsAllDrives": "true"},
                                  data=contenido, headers={"Content-Type": "text/html"}, timeout=300),
                       f"reemplazar «{nombre}»")
        else:
            meta = {"name": nombre, "parents": [padre]}
            fid = _comprobar(dr.s.post(UPLOAD, params={"uploadType": "multipart", "supportsAllDrives": "true", "fields": "id"},
                                       files={"metadata": ("metadata", json.dumps(meta), "application/json; charset=UTF-8"),
                                              "file": (nombre, contenido, "text/html")}, timeout=300),
                             f"subir «{nombre}»")["id"]
        enlaces_archivos[nombre] = ENLACE_ARCHIVO.format(fid)
    return usadas, enlaces_archivos
