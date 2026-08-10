import os
import re
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import weather

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
WEATHER_ENABLED = os.environ.get("WEATHER_ENABLED", "true").lower() != "false"
DEFAULT_CITY = os.environ.get("DEFAULT_CITY", "Jacareí")  # cidade padrão p/ previsão

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
         "sexta-feira", "sábado", "domingo"]

# Palavras que indicam pergunta sobre clima/tempo (evita o bare "tempo" p/ não confundir com duração).
_WEATHER_KW = [
    "previsão", "previsao", "clima", "chuva", "chover", "chovendo", "choveu",
    "temperatura", "graus", "ensolarad", "nublad", "umidade", "faz frio", "faz calor",
    "tá frio", "ta frio", "tá calor", "ta calor", "está frio", "está calor",
    "do tempo", "tempo em", "tempo hoje", "tempo amanhã", "tempo amanha",
    "tempo essa", "tempo nessa", "tempo esta", "tempo nesta",
]

# Cidade lembrada por chat (para previsão do tempo). Começa no padrão.
chat_city: dict[int, str] = {}


def is_weather_question(text):
    t = text.lower()
    return any(kw in t for kw in _WEATHER_KW)


def extract_city(text):
    """Tenta achar a cidade citada após 'em/para/pra/no/na'. O Open-Meteo valida depois."""
    m = re.search(
        r"\b(?:em|para|pra|no|na)\s+([A-Za-zÀ-ÿ][\wÀ-ÿ'\.]+(?:[\s\-][A-Za-zÀ-ÿ][\wÀ-ÿ'\.]+){0,3})",
        text,
        re.IGNORECASE,
    )
    if not m:
        return None
    cand = m.group(1).strip(" ?.!,").rstrip(".")
    # descarta capturas óbvias que não são cidade
    if cand.lower() in {"casa", "breve", "seguida", "que", "geral", "dia", "semana"}:
        return None
    return cand


def weather_context(chat_id, text):
    """Se for pergunta de clima, busca dados reais e devolve um bloco de contexto (ou None)."""
    if not WEATHER_ENABLED or not is_weather_question(text):
        return None
    stored = chat_city.get(chat_id, DEFAULT_CITY)
    cidade = extract_city(text) or stored
    txt, err = weather.forecast_text(cidade)
    if err and cidade != stored:  # cidade extraída falhou → tenta a lembrada/padrão
        cidade = stored
        txt, err = weather.forecast_text(cidade)
    if txt:
        return (
            "DADOS REAIS DE PREVISÃO DO TEMPO (fonte Open-Meteo, use-os para responder "
            f"e NÃO invente nada além disto):\n{txt}"
        )
    return (
        f"O serviço de previsão do tempo não respondeu agora ({err}). "
        "Avise o usuário que não conseguiu consultar a previsão neste momento e não invente dados."
    )


def system_prompt_agora():
    """O modelo não tem relógio próprio — injetamos a data/hora real a cada mensagem."""
    now = datetime.now(ZoneInfo(TZ))
    dia = _DIAS[now.weekday()]
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"AGORA: hoje é {dia}, {now.strftime('%d/%m/%Y')}, e são {now.strftime('%H:%M')} "
        f"(horário de {TZ}). Ao falar de data, dia da semana ou hora, use EXATAMENTE "
        f"esses valores — não recalcule nem mude o dia da semana.\n"
        f"Você NÃO tem acesso à internet nem a dados em tempo real. Nunca invente "
        f"previsão do tempo, notícias, cotações, resultados ou qualquer informação que "
        f"exija consulta ao vivo. Se perguntarem algo assim, responda com clareza que "
        f"você não tem esse acesso, em vez de inventar dados."
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

    # Nome exato COM tag (Ollama guarda "hermes3" como "hermes3:latest").
    wanted = OLLAMA_MODEL if ":" in OLLAMA_MODEL else f"{OLLAMA_MODEL}:latest"
    tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10).json()
    names = [m.get("name", "") for m in tags.get("models", [])]
    if wanted in names:
        log.info("Modelo %s já presente. OK.", wanted)
        return

    log.info("Baixando modelo %s (pode demorar alguns minutos na primeira vez)...", OLLAMA_MODEL)
    with requests.post(f"{OLLAMA_URL}/api/pull", json={"name": OLLAMA_MODEL}, stream=True, timeout=None) as r:
        for line in r.iter_lines():
            if line:
                log.info("pull: %s", line.decode("utf-8", "ignore")[:200])
    log.info("Download concluído.")


def ask_hermes(chat_id, user_text, extra_context=None):
    msgs = [{"role": "system", "content": system_prompt_agora()}]
    if extra_context:
        msgs.append({"role": "system", "content": extra_context})
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
            f"/cidade <nome> — define sua cidade p/ previsão (atual: {chat_city.get(chat_id, DEFAULT_CITY)})\n"
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
    if cmd.startswith("/cidade"):
        nome = text.strip()[len("/cidade"):].strip()
        if not nome:
            send_message(chat_id, f"Sua cidade atual é: {chat_city.get(chat_id, DEFAULT_CITY)}.\nUse: /cidade São Paulo")
            return
        try:
            g = weather.geocode(nome)
        except Exception:
            g = None
        if not g:
            send_message(chat_id, f"Não encontrei a cidade '{nome}'. Tente o nome completo, ex: /cidade Campos do Jordão")
            return
        chat_city[chat_id] = g.get("name", nome)
        local = chat_city[chat_id] + (f", {g.get('admin1')}" if g.get("admin1") else "")
        send_message(chat_id, f"Cidade definida: {local}. ✅ Agora é só perguntar a previsão.")
        return

    send_typing(chat_id)
    try:
        ctx = weather_context(chat_id, text)
    except Exception:
        log.exception("Erro ao montar contexto de clima")
        ctx = None
    try:
        reply = ask_hermes(chat_id, text, extra_context=ctx)
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
