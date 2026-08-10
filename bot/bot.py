import os
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hermes-bot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "hermes3:3b")
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    "Você é o Hermes, um assistente útil e direto. Responda em português do Brasil.",
)
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "12"))  # mensagens (user+assistant) por chat
REQUEST_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))  # geração em CPU pode demorar
TZ = os.environ.get("TZ", "America/Sao_Paulo")  # fuso usado p/ informar data/hora ao modelo

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
         "sexta-feira", "sábado", "domingo"]


def system_prompt_agora():
    """O modelo não tem relógio próprio — injetamos a data/hora real a cada mensagem."""
    now = datetime.now(ZoneInfo(TZ))
    dia = _DIAS[now.weekday()]
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"Data e hora atuais (fuso {TZ}): {dia}, {now.strftime('%d/%m/%Y %H:%M')}. "
        f"Use esta informação quando perguntarem sobre data, dia ou hora."
    )

# Restringe o bot a chat_ids autorizados (lista separada por vírgula). Vazio = liberado p/ todos.
ALLOWED = {c.strip() for c in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if c.strip()}

TG = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# histórico em memória: chat_id -> list[{"role","content"}]
history: dict[int, list[dict]] = {}


def tg(method, **params):
    r = requests.post(f"{TG}/{method}", json=params, timeout=60)
    r.raise_for_status()
    return r.json()


def send_message(chat_id, text):
    # Telegram limita a 4096 chars por mensagem
    for i in range(0, len(text), 4000):
        tg("sendMessage", chat_id=chat_id, text=text[i:i + 4000])


def send_typing(chat_id):
    try:
        tg("sendChatAction", chat_id=chat_id, action="typing")
    except Exception:
        pass


def ensure_model():
    """Espera o Ollama subir e baixa o modelo se ainda não estiver presente. Idempotente."""
    log.info("Verificando modelo %s no Ollama em %s ...", OLLAMA_MODEL, OLLAMA_URL)
    for _ in range(60):
        try:
            requests.get(f"{OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
            break
        except Exception:
            log.info("Aguardando Ollama ficar disponível...")
            time.sleep(3)
    else:
        log.error("Ollama não respondeu a tempo — o bot vai tentar mesmo assim.")
        return

    tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10).json()
    names = [m.get("name", "") for m in tags.get("models", [])]
    if any(n == OLLAMA_MODEL or n.split(":")[0] == OLLAMA_MODEL.split(":")[0] for n in names):
        log.info("Modelo já presente. OK.")
        return

    log.info("Baixando modelo %s (pode demorar alguns minutos na primeira vez)...", OLLAMA_MODEL)
    with requests.post(f"{OLLAMA_URL}/api/pull", json={"name": OLLAMA_MODEL}, stream=True, timeout=None) as r:
        for line in r.iter_lines():
            if line:
                log.info("pull: %s", line.decode("utf-8", "ignore")[:200])
    log.info("Download concluído.")


def ask_hermes(chat_id, user_text):
    msgs = [{"role": "system", "content": system_prompt_agora()}]
    msgs += history.get(chat_id, [])
    msgs.append({"role": "user", "content": user_text})

    payload = {"model": OLLAMA_MODEL, "messages": msgs, "stream": False}
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    reply = r.json()["message"]["content"].strip()

    h = history.get(chat_id, [])
    h.append({"role": "user", "content": user_text})
    h.append({"role": "assistant", "content": reply})
    history[chat_id] = h[-MAX_HISTORY:]
    return reply


def handle(update):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    if not text:
        return

    if ALLOWED and str(chat_id) not in ALLOWED:
        log.warning("Chat não autorizado: %s", chat_id)
        send_message(chat_id, f"Acesso não autorizado. Seu chat_id é: {chat_id}")
        return

    cmd = text.strip().lower()
    if cmd in ("/start", "/help"):
        send_message(
            chat_id,
            "Olá! Eu sou o Hermes 🤖 rodando na sua VPS.\n"
            "Manda sua pergunta que eu respondo.\n\n"
            "/reset — apaga a memória da conversa\n"
            "/id — mostra seu chat_id",
        )
        return
    if cmd == "/reset":
        history.pop(chat_id, None)
        send_message(chat_id, "Memória da conversa apagada. 🧹")
        return
    if cmd == "/id":
        send_message(chat_id, f"Seu chat_id é: {chat_id}")
        return

    send_typing(chat_id)
    try:
        reply = ask_hermes(chat_id, text)
    except Exception as e:
        log.exception("Erro ao consultar Hermes")
        send_message(chat_id, f"⚠️ Erro ao gerar resposta: {e}")
        return
    send_message(chat_id, reply)


def main():
    ensure_model()
    log.info("Bot iniciado. Long polling...")
    offset = None
    while True:
        try:
            resp = requests.get(
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
            try:
                handle(update)
            except Exception:
                log.exception("Erro ao tratar update")


if __name__ == "__main__":
    main()
