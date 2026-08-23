"""O "cérebro" do spike — só uma resposta via Groq pra provar que funciona no WhatsApp.
Na fase 2, aqui entra o núcleo real do bot (roteamento de contas/compromissos + DB)."""
import os
import logging

import requests

log = logging.getLogger("hermes-wa-spike.brain")

GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
SYSTEM = (
    "Você é o Hermes, um assistente pessoal útil e direto. Responda em português do Brasil, "
    "de forma curta e amigável."
)


def responder(texto: str) -> str:
    if not GROQ_KEY:
        return f"🤖 (spike) Recebi sua mensagem: {texto}"
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": texto},
                ],
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception:
        log.exception("Falha no LLM (Groq)")
        return "Tive um problema pra responder agora. Pode tentar de novo?"
