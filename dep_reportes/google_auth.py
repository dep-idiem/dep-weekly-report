"""Credenciales OAuth de Google (app de escritorio, pantalla de consentimiento Interna).

Orden de carga:
1. Entorno (fase 3, GitHub Actions): GOOGLE_OAUTH_CLIENT_JSON (contenido del JSON del cliente) y
   GOOGLE_REFRESH_TOKEN. Sin archivos ni navegador.
2. Local: secrets/google_oauth_client.json + secrets/google_token.json. Si no hay token, abre el
   navegador una vez (InstalledAppFlow) y guarda el token de actualizacion.

Nunca se imprimen ni registran secretos.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

from dep_clickup.config import ROOT  # carga .env y truststore

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CLIENTE_JSON = ROOT / "secrets" / "google_oauth_client.json"
TOKEN_JSON = ROOT / "secrets" / "google_token.json"
TOKEN_URI = "https://oauth2.googleapis.com/token"


def _cliente(info: dict) -> dict:
    return info.get("installed") or info.get("web") or info


def credenciales_desde_entorno() -> Credentials | None:
    cliente, refresh = os.getenv("GOOGLE_OAUTH_CLIENT_JSON"), os.getenv("GOOGLE_REFRESH_TOKEN")
    if not (cliente and refresh):
        return None
    c = _cliente(json.loads(cliente))
    return Credentials(None, refresh_token=refresh, token_uri=c.get("token_uri", TOKEN_URI),
                       client_id=c["client_id"], client_secret=c["client_secret"], scopes=SCOPES)


def cargar_credenciales(interactivo: bool = True, cliente_json: Path = CLIENTE_JSON,
                        token_json: Path = TOKEN_JSON) -> Credentials:
    creds = credenciales_desde_entorno()
    desde_archivo = False
    if creds is None and token_json.exists():
        creds = Credentials.from_authorized_user_file(str(token_json), SCOPES)
        desde_archivo = True
    if creds is None:
        if not interactivo:
            raise RuntimeError("Sin credenciales de Google: definir GOOGLE_OAUTH_CLIENT_JSON y GOOGLE_REFRESH_TOKEN "
                               "(ver README, 'Reautenticar Google')")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(cliente_json), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True,
                                      authorization_prompt_message="Abriendo el navegador para iniciar sesion en Google...",
                                      success_message="Listo. Puede cerrar esta pestaña.")
        _guardar(creds, token_json)
    if not creds.valid:
        from google.auth.exceptions import RefreshError
        try:
            creds.refresh(Request())
        except RefreshError as e:
            # Tipico: el refresh token fue revocado (cambio de contraseña, revocacion manual, 6 meses sin uso).
            raise RuntimeError(f"Google rechazó el refresh token ({type(e).__name__}): reautenticar Google "
                               "(ver README, 'Reautenticar Google')") from None
        if desde_archivo:
            _guardar(creds, token_json)
    return creds


def _guardar(creds: Credentials, token_json: Path) -> None:
    token_json.parent.mkdir(parents=True, exist_ok=True)
    token_json.write_text(creds.to_json(), encoding="utf-8")


def sesion(interactivo: bool = True) -> AuthorizedSession:
    return AuthorizedSession(cargar_credenciales(interactivo))
