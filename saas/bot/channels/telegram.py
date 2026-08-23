"""Adaptador de canal Telegram: transporte (send/typing/voice + baixar áudio),
normalização de updates para `Inbound` e o loop de long polling que chama o núcleo.

Identidade do canal: TelegramUserId (o chat_id de conversas 1:1). Registrado como
sender 'telegram' para que o agendador entregue lembretes por aqui.
"""
import os
import time
import socket
import logging

import requests

import config
import engine
import channels.base as channels

log = logging.getLogger("hermes.telegram")

# Opcional: um deploy pode rodar só WhatsApp. Sem token, o canal Telegram não sobe.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def enabled() -> bool:
    return bool(TELEGRAM_TOKEN)

# --- Força IPv4 -------------------------------------------------------------
# Em máquinas com IPv6 quebrado, cada conexão NOVA trava ~21s no timeout do SYN antes
# de cair pro IPv4. Filtrando o getaddrinfo para IPv4 o handshake volta ao normal.
# Seguro: se não houver IPv4, mantém a lista original. Desligue com FORCE_IPV4=0.
if os.environ.get("FORCE_IPV4", "1").lower() not in ("0", "false", "no"):
    _orig_getaddrinfo = socket.getaddrinfo

    def _getaddrinfo_ipv4(*args, **kwargs):
        res = _orig_getaddrinfo(*args, **kwargs)
        v4 = [r for r in res if r[0] == socket.AF_INET]
        return v4 or res

    socket.getaddrinfo = _getaddrinfo_ipv4

# Sessão HTTP reutilizável (keep-alive): evita refazer o handshake TLS a cada chamada.
SESSION = requests.Session()


def _tg(method, **params):
    t0 = time.perf_counter()
    r = SESSION.post(f"{TG}/{method}", json=params, timeout=60)
    r.raise_for_status()
    if config.TIMING:
        log.info("[t] TG %s: %.0f ms", method, (time.perf_counter() - t0) * 1000)
    return r.json()


class TelegramSender(channels.Sender):
    canal = "telegram"

    def send_text(self, identificador, text):
        # Telegram limita a 4096 chars por mensagem.
        for i in range(0, len(text), 4000):
            _tg("sendMessage", chat_id=identificador, text=text[i:i + 4000])

    def send_typing(self, identificador):
        try:
            _tg("sendChatAction", chat_id=identificador, action="typing")
        except Exception:
            pass

    def send_voice(self, identificador, audio_bytes, caption=None) -> bool:
        data = {"chat_id": identificador}
        if caption:
            data["caption"] = caption[:1000]
        r = SESSION.post(
            f"{TG}/sendVoice",
            data=data,
            files={"voice": ("lembrete.ogg", audio_bytes, "audio/ogg")},
            timeout=60,
        )
        r.raise_for_status()
        return True

    def baixar_audio(self, voice_ref):
        """voice_ref = file_id do Telegram. Retorna (bytes, filename, mime) ou None."""
        try:
            info = SESSION.get(f"{TG}/getFile", params={"file_id": voice_ref}, timeout=30).json()
            file_path = info["result"]["file_path"]
            audio = SESSION.get(
                f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}", timeout=60
            ).content
            return audio, "audio.ogg", "audio/ogg"
        except Exception:
            log.exception("Falha ao baixar áudio do Telegram")
            return None


SENDER = TelegramSender()


def _to_inbound(update) -> channels.Inbound | None:
    """Normaliza um update do Telegram para Inbound (mensagem 1:1). None se não aplicável."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    chat_id = msg["chat"]["id"]
    frm = msg.get("from") or {}
    voz = msg.get("voice") or msg.get("audio")
    return channels.Inbound(
        canal="telegram",
        identificador=str(chat_id),
        nome=frm.get("username"),
        text=msg.get("text", "") or "",
        voice_ref=(voz.get("file_id") if voz else None),
        voice_seg=int(voz.get("duration") or 0) if voz else 0,
    )


def poll_loop():
    """Long polling: recebe updates e delega ao núcleo. Bloqueante — rode em thread própria."""
    if not TELEGRAM_TOKEN:
        log.warning("TELEGRAM_TOKEN ausente — canal Telegram não iniciado.")
        return
    channels.register(SENDER)
    log.info("Canal Telegram: long polling iniciado.")
    offset = None
    while True:
        try:
            resp = SESSION.get(
                f"{TG}/getUpdates",
                params={"timeout": 30, "offset": offset},
                timeout=40,
            ).json()
        except Exception as e:
            log.warning("getUpdates falhou: %s", e)
            time.sleep(3)
            continue

        for update in resp.get("result", []):
            offset = update["update_id"] + 1
            t0 = time.perf_counter()
            try:
                inbound = _to_inbound(update)
                if inbound is not None:
                    engine.processar(inbound, SENDER)
            except Exception:
                log.exception("Erro ao tratar update do Telegram")
            if config.TIMING:
                log.info("[t] update total: %.0f ms", (time.perf_counter() - t0) * 1000)
