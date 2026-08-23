"""Entrypoint do Hermes multi-canal (processo único).

Sobe, no MESMO processo:
- o agendador (thread) — entrega lembretes no canal em que cada tenant está conectado;
- o canal Telegram (long polling), se TELEGRAM_TOKEN estiver definido;
- o canal WhatsApp (webhook FastAPI/UAZAPI), se UAZAPI_BASE_URL+UAZAPI_TOKEN estiverem definidos.

Se ambos os canais estiverem ativos, o WhatsApp roda o servidor web (bloqueante) e o
Telegram roda numa thread. Se só o Telegram estiver ativo, ele roda bloqueante (sem
servidor web). Cada canal é independente: dá pra rodar só um dos dois.
"""
import os
import logging
import threading

import config
import db
import llm
import engine
import channels.base as channels
from channels import telegram, whatsapp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hermes")

TELEGRAM_ENABLED = telegram.enabled()
WHATSAPP_ENABLED = bool(os.environ.get("UAZAPI_BASE_URL") and os.environ.get("UAZAPI_TOKEN"))
PORT = int(os.environ.get("PORT", "8080"))


def main():
    db.ping()  # falha rápido se o MySQL não estiver acessível

    if config.LLM_PROVIDER == "groq":
        log.info("Cérebro: GROQ (nuvem), modelo %s.", config.GROQ_MODEL)
    else:
        log.info("Cérebro: OLLAMA (local), modelo %s.", config.OLLAMA_MODEL)
        llm.ensure_model()

    if config.BILLS_ENABLED or config.REMINDERS_ENABLED:
        threading.Thread(target=engine.scheduler_loop, daemon=True).start()

    ativos = [c for c, on in (("Telegram", TELEGRAM_ENABLED), ("WhatsApp", WHATSAPP_ENABLED)) if on]
    if not ativos:
        raise SystemExit("Nenhum canal configurado. Defina TELEGRAM_TOKEN e/ou UAZAPI_BASE_URL+UAZAPI_TOKEN.")
    log.info("Hermes iniciado. Canais ativos: %s.", ", ".join(ativos))

    if WHATSAPP_ENABLED:
        channels.register(whatsapp.SENDER)
        if TELEGRAM_ENABLED:
            # Telegram na thread; WhatsApp (servidor web) bloqueia a main.
            threading.Thread(target=telegram.poll_loop, daemon=True).start()
        import uvicorn
        uvicorn.run(whatsapp.build_app(), host="0.0.0.0", port=PORT, log_level="info")
    else:
        # Só Telegram: long polling bloqueia a main (sem servidor web).
        telegram.poll_loop()


if __name__ == "__main__":
    main()
