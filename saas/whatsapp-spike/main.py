"""Spike Hermes no WhatsApp via UAZAPI — PROVA DE CONCEITO (isolado do bot real).

Fluxo: UAZAPI recebe a mensagem no WhatsApp → chama nosso /webhook → extraímos
número+texto → geramos a resposta (Groq) → enviamos de volta via UAZAPI.

Objetivo do spike: provar que dá pra receber e responder no WhatsApp com o mesmo
"cérebro". NÃO tem multi-tenant/DB ainda (isso é a fase 2).
"""
import os
import logging

from fastapi import FastAPI, Request, HTTPException

import uazapi
import brain

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")  # opcional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hermes-wa-spike")

app = FastAPI(title="Hermes WhatsApp Spike")


@app.get("/")
def health():
    return {"ok": True, "service": "hermes-whatsapp-spike"}


@app.post("/webhook")
async def webhook(req: Request):
    if WEBHOOK_SECRET:
        enviado = req.headers.get("x-webhook-secret") or req.query_params.get("secret") or ""
        if enviado != WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        payload = await req.json()
    except Exception:
        log.warning("Webhook sem JSON válido.")
        return {"ignored": True}

    # 1º objetivo do spike: VER o formato real do payload do seu UAZAPI.
    log.info("WEBHOOK payload: %s", payload)

    msg = uazapi.parse_incoming(payload)
    if not msg:
        return {"ignored": True, "motivo": "não reconheci a mensagem"}

    numero, texto, from_me = msg["numero"], msg["texto"], msg["from_me"]
    if from_me or not texto:
        return {"ignored": True, "motivo": "mensagem própria ou sem texto"}

    log.info("Recebido de %s: %s", numero, texto)
    resposta = brain.responder(texto)
    uazapi.send_text(numero, resposta)
    return {"ok": True}
