"""Entrypoint do Hermes (processo único).

Sobe, no MESMO processo:
- o agendador (thread) — entrega lembretes/contas no WhatsApp de cada tenant;
- o canal WhatsApp (webhook FastAPI/UAZAPI), servindo em PORT (default 8080).

O canal WhatsApp exige UAZAPI_BASE_URL + UAZAPI_TOKEN no Environment; o webhook do
UAZAPI deve apontar para https://<dominio-do-bot>/webhook.
"""
import os
import logging
import threading

import config
import db
import llm
import engine
import channels.base as channels
from channels import whatsapp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hermes")

WHATSAPP_ENABLED = bool(os.environ.get("UAZAPI_BASE_URL") and os.environ.get("UAZAPI_TOKEN"))
PORT = int(os.environ.get("PORT", "8080"))


def main():
    db.ping()  # falha rápido se o MySQL não estiver acessível

    if not WHATSAPP_ENABLED:
        raise SystemExit("Canal WhatsApp não configurado. Defina UAZAPI_BASE_URL e UAZAPI_TOKEN.")

    if config.LLM_PROVIDER == "groq":
        log.info("Cérebro: GROQ (nuvem), modelo %s.", config.GROQ_MODEL)
    else:
        log.info("Cérebro: OLLAMA (local), modelo %s.", config.OLLAMA_MODEL)
        llm.ensure_model()

    if config.BILLS_ENABLED or config.REMINDERS_ENABLED:
        threading.Thread(target=engine.scheduler_loop, daemon=True).start()

    channels.register(whatsapp.SENDER)
    log.info("Hermes iniciado. Canal ativo: WhatsApp (webhook na porta %s).", PORT)

    import uvicorn
    uvicorn.run(whatsapp.build_app(), host="0.0.0.0", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
