"""Camada de transporte UAZAPI (enviar/receber WhatsApp).

⚠️ A API do UAZAPI varia por versão/instância. Os padrões abaixo são configuráveis
por env. CONFIRME o endpoint de envio e o formato do webhook com a sua instância
(ou com o código do Agente Clínica, que já usa UAZAPI) e ajuste se preciso.
"""
import os
import logging

import requests

log = logging.getLogger("hermes-wa-spike.uazapi")

BASE = os.environ.get("UAZAPI_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("UAZAPI_TOKEN", "")
# Caminho do endpoint de envio de texto. Padrão comum do UAZAPI: /send/text
SEND_PATH = os.environ.get("UAZAPI_SEND_PATH", "/send/text")
# Nome do header de autenticação (UAZAPI costuma usar "token").
TOKEN_HEADER = os.environ.get("UAZAPI_TOKEN_HEADER", "token")


def send_text(numero: str, texto: str):
    """Envia uma mensagem de texto pelo WhatsApp via UAZAPI."""
    if not BASE or not TOKEN:
        log.warning("UAZAPI não configurado (UAZAPI_BASE_URL/UAZAPI_TOKEN). Não enviei.")
        return
    url = f"{BASE}{SEND_PATH}"
    try:
        r = requests.post(
            url,
            headers={TOKEN_HEADER: TOKEN, "Content-Type": "application/json"},
            json={"number": numero, "text": texto},
            timeout=30,
        )
        r.raise_for_status()
        log.info("Enviado p/ %s (HTTP %s)", numero, r.status_code)
    except Exception:
        log.exception("Falha ao enviar via UAZAPI (confira BASE_URL/SEND_PATH/token)")


def parse_incoming(payload: dict) -> dict | None:
    """Extrai {numero, texto, from_me} de vários formatos possíveis do UAZAPI.
    Ajuste conforme o payload REAL que aparecer no log do /webhook."""
    if not isinstance(payload, dict):
        return None
    # o objeto da mensagem pode vir em 'message', 'data', ou na raiz
    m = payload.get("message") or payload.get("data") or payload
    if not isinstance(m, dict):
        return None

    key = m.get("key") if isinstance(m.get("key"), dict) else {}
    from_me = bool(m.get("fromMe") or key.get("fromMe"))

    numero = (
        m.get("number") or m.get("sender") or m.get("chatid") or m.get("from")
        or key.get("remoteJid") or ""
    )
    numero = str(numero).split("@")[0].split(":")[0]

    inner = m.get("message") if isinstance(m.get("message"), dict) else {}
    texto = (
        m.get("text") or m.get("body") or m.get("conversation")
        or inner.get("conversation")
        or (inner.get("extendedTextMessage") or {}).get("text")
        or ""
    )

    if not numero:
        return None
    return {"numero": numero, "texto": texto, "from_me": from_me}
