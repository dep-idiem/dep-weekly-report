"""Cliente de solo lectura de la API de Google Drive v3.

Usa el mismo cliente OAuth del worker de reportes (secrets/google_oauth_client.json, cuenta
institucional), pero con un token propio de alcance drive.readonly en secrets/google_token_drive.json:
el token del worker solo tiene el alcance de Sheets y no se toca. La primera vez abre el navegador
para dar el consentimiento. En CI se usaria GOOGLE_REFRESH_TOKEN_DRIVE (no hay CI en esta fase).

Solo GET. Cachea por corrida los metadatos y los hijos de cada carpeta. Nunca imprime secretos.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

from dep_reportes.google_auth import CLIENTE_JSON, TOKEN_URI, _cliente, _guardar
from dep_clickup.config import ROOT

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
TOKEN_DRIVE_JSON = ROOT / "secrets" / "google_token_drive.json"
API = "https://www.googleapis.com/drive/v3"
FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
CAMPOS_ARCHIVO = ("id,name,mimeType,size,modifiedTime,parents,driveId,trashed,"
                  "lastModifyingUser(displayName,emailAddress),shortcutDetails(targetId,targetMimeType)")

_RE_ID = [re.compile(p) for p in (r"/folders/([A-Za-z0-9_-]{10,})", r"[?&]id=([A-Za-z0-9_-]{10,})",
                                  r"/d/([A-Za-z0-9_-]{10,})")]


def id_desde_url(url: str | None) -> str | None:
    """ID de carpeta/archivo de un link de Drive; None si el texto no lo trae."""
    if not url:
        return None
    for r in _RE_ID:
        m = r.search(url)
        if m:
            return m.group(1)
    return None


def cargar_credenciales(interactivo: bool = True, token_json: Path = TOKEN_DRIVE_JSON) -> Credentials:
    refresh = os.getenv("GOOGLE_REFRESH_TOKEN_DRIVE")
    if refresh and os.getenv("GOOGLE_OAUTH_CLIENT_JSON"):
        c = _cliente(json.loads(os.environ["GOOGLE_OAUTH_CLIENT_JSON"]))
        creds = Credentials(None, refresh_token=refresh, token_uri=c.get("token_uri", TOKEN_URI),
                            client_id=c["client_id"], client_secret=c["client_secret"], scopes=SCOPES)
        desde_archivo = False
    elif token_json.exists():
        creds = Credentials.from_authorized_user_file(str(token_json), SCOPES)
        desde_archivo = True
    else:
        if not interactivo:
            raise RuntimeError(f"Sin token de Drive ({token_json.name}): correr una vez en local con navegador")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENTE_JSON), SCOPES)
        creds = flow.run_local_server(
            port=0, open_browser=True,
            authorization_prompt_message="Abriendo el navegador para dar acceso de LECTURA a Drive (cuenta institucional)...",
            success_message="Listo. Puede cerrar esta pestaña.")
        _guardar(creds, token_json)
        return creds
    if not creds.valid:
        creds.refresh(Request())
        if desde_archivo:
            _guardar(creds, token_json)
    return creds


class DriveError(RuntimeError):
    def __init__(self, status: int, path: str, body: str):
        super().__init__(f"Drive {status} en GET {path}: {body[:300]}")
        self.status = status


class DriveClient:
    def __init__(self, session: AuthorizedSession | None = None, *, min_intervalo: float = 0.05,
                 max_reintentos: int = 5, sleep=time.sleep):
        self.s = session or AuthorizedSession(cargar_credenciales())
        self.min_intervalo = min_intervalo
        self.max_reintentos = max_reintentos
        self._sleep = sleep
        self._ultimo = 0.0
        self.request_count = 0
        self._meta: dict[str, dict | DriveError] = {}
        self._hijos: dict[str, list[dict]] = {}

    def _get(self, path: str, params: dict) -> dict:
        params = {"supportsAllDrives": "true", **params}
        for intento in range(self.max_reintentos + 1):
            espera = self.min_intervalo - (time.monotonic() - self._ultimo)
            if espera > 0:
                self._sleep(espera)
            self._ultimo = time.monotonic()
            self.request_count += 1
            r = self.s.get(API + path, params=params, timeout=60)
            limite = r.status_code == 429 or r.status_code >= 500 or (
                r.status_code == 403 and ("rateLimitExceeded" in r.text or "userRateLimitExceeded" in r.text))
            if limite and intento < self.max_reintentos:
                self._sleep(min(60, 2 ** (intento + 1)))
                continue
            if r.status_code != 200:
                raise DriveError(r.status_code, path, r.text)
            return r.json()
        raise AssertionError("inalcanzable")

    def about(self) -> dict:
        return self._get("/about", {"fields": "user(displayName,emailAddress)"})

    def meta(self, file_id: str) -> dict:
        """Metadatos del archivo/carpeta (cacheados, tambien los errores). Lanza DriveError si no resuelve."""
        if file_id not in self._meta:
            try:
                self._meta[file_id] = self._get(f"/files/{file_id}", {"fields": CAMPOS_ARCHIVO})
            except DriveError as e:
                self._meta[file_id] = e
        m = self._meta[file_id]
        if isinstance(m, DriveError):
            raise m
        return m

    def resolver_carpeta(self, file_id: str) -> dict:
        """Como meta(), siguiendo un acceso directo hasta su destino."""
        m = self.meta(file_id)
        if m.get("mimeType") == SHORTCUT and (m.get("shortcutDetails") or {}).get("targetId"):
            return self.meta(m["shortcutDetails"]["targetId"])
        return m

    def hijos(self, folder_id: str) -> list[dict]:
        """Hijos directos (no recursivo), sin papelera. Cacheado."""
        if folder_id not in self._hijos:
            out, token = [], None
            while True:
                p = {"q": f"'{folder_id}' in parents and trashed=false", "pageSize": 1000,
                     "includeItemsFromAllDrives": "true", "fields": f"nextPageToken,files({CAMPOS_ARCHIVO})"}
                if token:
                    p["pageToken"] = token
                data = self._get("/files", p)
                out.extend(data.get("files", []))
                token = data.get("nextPageToken")
                if not token:
                    break
            for f in out:
                self._meta.setdefault(f["id"], f)
            self._hijos[folder_id] = out
        return self._hijos[folder_id]
