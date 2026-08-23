"""Adaptador de canal WhatsApp via UAZAPI: transporte (envio de texto, download de
áudio recebido), normalização do webhook para `Inbound` e a app FastAPI que recebe
os eventos e delega ao núcleo.

Identidade do canal: telefone só dígitos (E.164 sem '+'). Registrado como sender
'whatsapp' para que o agendador entregue lembretes por aqui.

Contrato UAZAPI (mesmo do Agente Clínica, produção):
- ENVIO texto:  POST {BASE}/send/text  header {token}  body {number, text}
- WEBHOOK:      mensagem em payload["message"]; remetente em sender_pn; texto em
                text/content; tipo em type/messageType ('audio'/'ptt'); id em id/messageid.
- DOWNLOAD:     URL no content (se http) OU GET {BASE}/downloadMedia?id={id} -> {base64|data}.
- ENVIO áudio:  não implementado (sem contrato provado) -> lembrete de voz cai p/ texto.
"""
import os
import base64
import logging

import requests
from fastapi import FastAPI, Request, HTTPException
from starlette.concurrency import run_in_threadpool

import engine
import channels.base as channels

log = logging.getLogger("hermes.whatsapp")

BASE = os.environ.get("UAZAPI_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("UAZAPI_TOKEN", "")
SEND_PATH = os.environ.get("UAZAPI_SEND_PATH", "/send/text")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")  # opcional


def _limpar_numero(v) -> str:
    return (
        str(v or "")
        .replace("@s.whatsapp.net", "")
        .replace("@c.us", "")
        .replace("+", "").replace(" ", "").replace("-", "")
        .strip()
    )


class WhatsAppSender(channels.Sender):
    canal = "whatsapp"

    def send_text(self, identificador, text):
        if not BASE or not TOKEN:
            log.warning("UAZAPI não configurado (UAZAPI_BASE_URL/UAZAPI_TOKEN). Não enviei.")
            return
        try:
            r = requests.post(
                f"{BASE}{SEND_PATH}",
                headers={"token": TOKEN, "Content-Type": "application/json"},
                json={"number": _limpar_numero(identificador), "text": text},
                timeout=30,
            )
            r.raise_for_status()
        except Exception:
            log.exception("Falha ao enviar texto via UAZAPI")

    def send_typing(self, identificador):
        # UAZAPI não expõe "digitando" de forma simples; no-op (o texto já basta).
        return None

    def send_voice(self, identificador, audio_bytes, caption=None) -> bool:
        # Envio de áudio no WhatsApp ainda não implementado (sem contrato UAZAPI provado).
        # Retorna False -> o engine entrega o lembrete como TEXTO.
        return False

    def baixar_audio(self, voice_ref):
        """voice_ref = {"id": message_id, "url": url_ou_None}. Retorna (bytes, filename, mime) ou None."""
        if not isinstance(voice_ref, dict):
            return None
        url = voice_ref.get("url")
        # 1) URL direta no webhook
        if url and str(url).startswith("http"):
            try:
                r = requests.get(url, timeout=60)
                r.raise_for_status()
                return r.content, "audio.ogg", "audio/ogg"
            except Exception:
                log.exception("Falha ao baixar áudio pela URL do webhook")
        # 2) Fallback: endpoint downloadMedia pelo id da mensagem
        mid = voice_ref.get("id")
        if mid and BASE and TOKEN:
            try:
                r = requests.get(
                    f"{BASE}/downloadMedia",
                    headers={"token": TOKEN},
                    params={"id": mid},
                    timeout=60,
                )
                r.raise_for_status()
                data = r.json()
                b64 = data.get("base64") or data.get("data") or ""
                if "," in b64:
                    b64 = b64.split(",", 1)[1]
                if b64:
                    return base64.b64decode(b64), "audio.ogg", "audio/ogg"
            except Exception:
                log.exception("Falha ao baixar áudio via downloadMedia")
        return None


SENDER = WhatsAppSender()


def parse_incoming(payload: dict) -> channels.Inbound | None:
    """Normaliza o webhook do UAZAPI para Inbound. None se não for mensagem de texto/áudio
    válida (status, grupo, ou enviada pelo próprio bot)."""
    if not isinstance(payload, dict):
        return None

    evento = payload.get("EventType") or payload.get("wook") or ""
    if evento and evento not in ("messages", "RECEIVE_MESSAGE"):
        return None

    msg = payload.get("message") if isinstance(payload.get("message"), dict) else payload
    if not isinstance(msg, dict):
        return None

    if bool(msg.get("fromMe") or msg.get("wasSentByApi")):
        return None
    if bool(msg.get("isGroup") or (payload.get("chat") or {}).get("wa_isGroup")):
        return None

    numero = _limpar_numero(msg.get("sender_pn") or msg.get("sender") or "")
    if not numero:
        return None

    nome = msg.get("senderName") or msg.get("pushName") or msg.get("name")
    tipo = (msg.get("type") or msg.get("messageType") or "text").lower()
    content = msg.get("text") or msg.get("content") or ""

    if tipo in ("audio", "ptt"):
        mid = msg.get("messageid") or msg.get("id") or ""
        url = content if str(content).startswith("http") else None
        try:
            seg = int(msg.get("seconds") or msg.get("duration") or 0)
        except (TypeError, ValueError):
            seg = 0
        return channels.Inbound(
            canal="whatsapp", identificador=numero, nome=nome,
            text="", voice_ref={"id": mid, "url": url}, voice_seg=seg,
        )

    return channels.Inbound(canal="whatsapp", identificador=numero, nome=nome, text=content)


def build_app() -> FastAPI:
    """FastAPI que recebe o webhook do UAZAPI e delega ao núcleo. O núcleo é síncrono
    e faz IO bloqueante (LLM/DB) -> roda em threadpool p/ não travar o event loop."""
    app = FastAPI(title="Hermes WhatsApp")

    @app.get("/")
    def health():
        return {"ok": True, "service": "hermes-whatsapp", "canal": "whatsapp"}

    @app.post("/webhook")
    async def webhook(req: Request):
        if WEBHOOK_SECRET:
            enviado = req.headers.get("x-webhook-secret") or req.query_params.get("secret") or ""
            if enviado != WEBHOOK_SECRET:
                raise HTTPException(status_code=401, detail="Unauthorized")
        try:
            payload = await req.json()
        except Exception:
            return {"ignored": True}

        inbound = parse_incoming(payload)
        if inbound is None:
            return {"ignored": True}
        try:
            await run_in_threadpool(engine.processar, inbound, SENDER)
        except Exception:
            log.exception("Erro ao processar mensagem do WhatsApp")
        return {"ok": True}

    return app
