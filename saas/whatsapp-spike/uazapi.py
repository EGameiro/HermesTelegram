"""Camada de transporte UAZAPI (enviar/receber WhatsApp).

Alinhado ao formato usado no Agente Clínica (mesma versão do UAZAPI):
- ENVIO:  POST {BASE}/send/text  headers {token}  body {number, text}
- WEBHOOK: EventType="messages" (ou wook="RECEIVE_MESSAGE"), objeto em payload["message"],
  remetente em sender_pn, texto em text/content; ignora fromMe/wasSentByApi/isGroup.
"""
import os
import logging

import requests

log = logging.getLogger("hermes-wa-spike.uazapi")

BASE = os.environ.get("UAZAPI_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("UAZAPI_TOKEN", "")
SEND_PATH = os.environ.get("UAZAPI_SEND_PATH", "/send/text")


def _limpar_numero(v: str) -> str:
    return (
        str(v or "")
        .replace("@s.whatsapp.net", "")
        .replace("@c.us", "")
        .replace("+", "")
        .replace(" ", "")
        .replace("-", "")
        .strip()
    )


def send_text(numero: str, texto: str):
    """Envia uma mensagem de texto pelo WhatsApp via UAZAPI."""
    if not BASE or not TOKEN:
        log.warning("UAZAPI não configurado (UAZAPI_BASE_URL/UAZAPI_TOKEN). Não enviei.")
        return
    url = f"{BASE}{SEND_PATH}"
    try:
        r = requests.post(
            url,
            headers={"token": TOKEN, "Content-Type": "application/json"},
            json={"number": _limpar_numero(numero), "text": texto},
            timeout=30,
        )
        r.raise_for_status()
        log.info("Enviado p/ %s (HTTP %s)", numero, r.status_code)
    except Exception:
        log.exception("Falha ao enviar via UAZAPI")


def parse_incoming(payload: dict) -> dict | None:
    """Extrai {numero, texto, from_me} do webhook do UAZAPI. Retorna None se não for
    uma mensagem de texto válida (evento de status, grupo, ou enviada pelo próprio bot)."""
    if not isinstance(payload, dict):
        return None

    # só eventos de mensagem recebida
    evento = payload.get("EventType") or payload.get("wook") or ""
    if evento and evento not in ("messages", "RECEIVE_MESSAGE"):
        return None

    # formato novo: objeto em 'message'; formato antigo: campos na raiz
    msg = payload.get("message") if isinstance(payload.get("message"), dict) else payload
    if not isinstance(msg, dict):
        return None

    from_me = bool(msg.get("fromMe") or msg.get("wasSentByApi"))
    is_group = bool(msg.get("isGroup") or (payload.get("chat") or {}).get("wa_isGroup"))
    if is_group:
        return None

    numero = _limpar_numero(msg.get("sender_pn") or msg.get("sender") or "")
    texto = msg.get("text") or msg.get("content") or ""
    if not numero:
        return None
    return {"numero": numero, "texto": texto, "from_me": from_me}
