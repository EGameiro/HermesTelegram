"""Espelhamento de compromissos na Google Agenda (mão única: Hermes -> Google).

O painel faz o OAuth e guarda, por usuário, um RefreshToken + a agenda escolhida em
H01GoogleAgenda. Aqui o bot troca o refresh token por um access token (cacheado em
memória enquanto válido) e cria/apaga eventos via Google Calendar API.

Tudo é BEST-EFFORT: se o usuário não conectou o Google, se o token foi revogado ou a
API falhar, as funções retornam None/False e o Hermes segue funcionando normal (o
compromisso continua salvo no banco e o lembrete pelo WhatsApp acontece do mesmo jeito).

Um evento por ocorrência (compromissos recorrentes viram N eventos independentes).
"""
import time
import logging
from datetime import datetime, timedelta

import requests

import config
import db

log = logging.getLogger("hermes.gcal")

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_API = "https://www.googleapis.com/calendar/v3"
_SESSION = requests.Session()

# Cache de access tokens por refresh token: {refresh_token: (access_token, expira_em_epoch)}.
_tok_cache: dict[str, tuple[str, float]] = {}
# Cache da conta Google por usuário (evita reler o banco a cada ocorrência de uma série).
_conta_cache: dict[int, tuple[dict | None, float]] = {}
_CONTA_TTL = 30  # s — curto: reflete conectar/desconectar no painel em até 30s.

# Duração padrão de um evento (min) — compromissos são pontuais; damos 1h de bloco.
_DUR_MIN = 60


def _conta(usuario_id):
    """Linha de H01GoogleAgenda do usuário se estiver CONECTADO e com agenda definida
    (ou None). Cacheada por _CONTA_TTL segundos."""
    if not config.GCAL_ENABLED:
        return None
    ent = _conta_cache.get(usuario_id)
    if ent and ent[1] > time.time():
        return ent[0]
    row = db.query_one(
        "SELECT RefreshToken, CalendarId, StatusConexao "
        "FROM H01GoogleAgenda WHERE UsuarioId = %s",
        (usuario_id,),
    )
    conta = row if (row and row.get("StatusConexao") == "conectado"
                    and row.get("RefreshToken") and row.get("CalendarId")) else None
    _conta_cache[usuario_id] = (conta, time.time() + _CONTA_TTL)
    return conta


def _access_token(refresh_token):
    """Troca o refresh token por um access token (cacheado até ~1 min antes de expirar)."""
    cached = _tok_cache.get(refresh_token)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    try:
        r = _SESSION.post(_TOKEN_URL, data={
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception:
        log.warning("Falha ao renovar access token do Google", exc_info=True)
        return None
    tok = data.get("access_token")
    if not tok:
        return None
    exp = time.time() + int(data.get("expires_in", 3600))
    _tok_cache[refresh_token] = (tok, exp)
    return tok


def criar_evento(usuario_id, descricao, quando_iso, tz=None):
    """Cria um evento na agenda do usuário. Retorna o event_id (str) ou None.

    quando_iso: 'YYYY-MM-DDTHH:MM' (ou com segundos). tz: nome IANA do fuso do tenant."""
    conta = _conta(usuario_id)
    if not conta:
        return None
    token = _access_token(conta["RefreshToken"])
    if not token:
        return None
    try:
        inicio = datetime.fromisoformat(quando_iso)
    except Exception:
        log.warning("quando_iso inválido p/ Google (%r)", quando_iso)
        return None
    fim = inicio + timedelta(minutes=_DUR_MIN)
    tzname = tz or config.TZ
    body = {
        "summary": descricao,
        "description": "Criado pelo Hermes 🤖",
        "start": {"dateTime": inicio.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tzname},
        "end": {"dateTime": fim.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": tzname},
    }
    try:
        r = _SESSION.post(
            f"{_API}/calendars/{conta['CalendarId']}/events",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body, timeout=30,
        )
        r.raise_for_status()
        return r.json().get("id")
    except Exception:
        log.warning("Falha ao criar evento no Google (usuario %s)", usuario_id, exc_info=True)
        return None


def apagar_evento(usuario_id, event_id):
    """Apaga o evento espelhado. Best-effort; retorna True se apagou (ou já não existia)."""
    if not event_id:
        return False
    conta = _conta(usuario_id)
    if not conta:
        return False
    token = _access_token(conta["RefreshToken"])
    if not token:
        return False
    try:
        r = _SESSION.delete(
            f"{_API}/calendars/{conta['CalendarId']}/events/{event_id}",
            headers={"Authorization": f"Bearer {token}"}, timeout=30,
        )
        # 200/204 = apagado; 404/410 = já não existe (tratamos como sucesso).
        if r.status_code in (200, 204, 404, 410):
            return True
        r.raise_for_status()
        return True
    except Exception:
        log.warning("Falha ao apagar evento no Google (usuario %s, ev %s)", usuario_id, event_id, exc_info=True)
        return False
