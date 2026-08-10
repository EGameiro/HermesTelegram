import os
import re
import json
import time
import logging
import threading
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import requests

import weather
import websearch
import bills

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
WEBSEARCH_ENABLED = os.environ.get("WEBSEARCH_ENABLED", "true").lower() != "false"
BILLS_ENABLED = os.environ.get("BILLS_ENABLED", "true").lower() != "false"
REMINDER_HOUR = int(os.environ.get("REMINDER_HOUR", "8"))  # hora do dia p/ enviar lembretes
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")  # p/ transcrever áudio (Whisper); vazio = voz off
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "whisper-1")
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "tts-1")  # texto->voz p/ lembretes
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "nova")
REMINDER_VOICE = os.environ.get("REMINDER_VOICE", "true").lower() != "false"  # lembrete em áudio

# Contas aguardando confirmação do usuário: chat_id -> {"descricao","valor","vencimento"}
pending_bill: dict[int, dict] = {}

_AFIRMATIVO = {"sim", "s", "confirmo", "confirmar", "ok", "isso", "pode", "salvar", "salva", "👍"}
_NEGATIVO = {"não", "nao", "n", "cancela", "cancelar", "negativo"}

# Frases que indicam pedido de busca na web (além do comando /buscar). Conservador p/ evitar
# disparar em toda pergunta comum (busca é lenta e pode ser bloqueada por excesso).
_WEB_KW = [
    "na internet", "na web", "no google", "pesquise", "pesquisa na", "pesquisar na",
    "notícia", "noticia", "novidades sobre", "últimas notícias", "ultimas noticias",
    "cotação", "cotacao", "o que estão falando", "o que estao falando", "acesse o site",
]

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


def web_query(text):
    """Devolve o termo a buscar (comando /buscar|/web ou gatilho natural), ou None."""
    if not WEBSEARCH_ENABLED:
        return None
    t = text.strip()
    low = t.lower()
    for pref in ("/buscar", "/web"):
        if low.startswith(pref):
            return t[len(pref):].strip() or None
    if any(kw in low for kw in _WEB_KW):
        return t
    return None


def web_context(text):
    """Se for pedido de busca, consulta a web e devolve o bloco de contexto (ou None)."""
    q = web_query(text)
    if not q:
        return None
    resultados, err = websearch.search(q)
    if resultados:
        return (
            f"RESULTADOS DE BUSCA NA WEB para \"{q}\" (use estes resultados para responder de "
            f"forma atualizada e CITE as fontes com o link; se não bastarem, diga o que "
            f"encontrou):\n\n{resultados}"
        )
    return (
        f"A busca na web não retornou resultados agora ({err}). Diga ao usuário que não "
        "conseguiu buscar e responda com o que souber, avisando que pode estar desatualizado."
    )


# ---------------------------------------------------------------------------
# Contas a pagar
# ---------------------------------------------------------------------------
_BILL_ADD_KW = ["lembr", "conta de", "conta da", "conta do", "boleto", "fatura", "vence", "pagar"]
_BILL_LIST_KW = [
    "minhas contas", "quais contas", "contas a pagar", "o que tenho pra pagar",
    "o que tenho para pagar", "lista de contas", "listar contas", "tenho pra pagar",
    "tenho para pagar", "quais são minhas contas",
]


def is_bill_add(text):
    if not BILLS_ENABLED:
        return False
    low = text.lower()
    return any(kw in low for kw in _BILL_ADD_KW) and any(ch.isdigit() for ch in low)


def is_bill_list(text):
    if not BILLS_ENABLED:
        return False
    low = text.lower()
    if low.strip() == "/contas":
        return True
    if any(kw in low for kw in _BILL_LIST_KW):
        return True
    # "quanto/total ... pagar" → também é consulta de contas
    if "pagar" in low and ("quanto" in low or "total" in low):
        return True
    return False


def _periodo(text):
    """Extrai o período da pergunta. Retorna (label, ini_iso, fim_iso); (None,None,None) = todas."""
    low = text.lower()
    hoje = date.today()

    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", low)
    if m:
        try:
            d, mth = int(m.group(1)), int(m.group(2))
            y = int(m.group(3)) if m.group(3) else hoje.year
            if y < 100:
                y += 2000
            alvo = date(y, mth, d)
            if alvo < hoje and not m.group(3):
                alvo = alvo.replace(year=alvo.year + 1)
            return (f"em {alvo.strftime('%d/%m/%Y')}", alvo.isoformat(), alvo.isoformat())
        except ValueError:
            pass

    m2 = re.search(r"\bdia\s+(\d{1,2})\b", low)
    if m2:
        try:
            d = int(m2.group(1))
            alvo = date(hoje.year, hoje.month, d)
            if alvo < hoje:
                alvo = (date(hoje.year + 1, 1, d) if hoje.month == 12
                        else date(hoje.year, hoje.month + 1, d))
            return (f"em {alvo.strftime('%d/%m/%Y')}", alvo.isoformat(), alvo.isoformat())
        except ValueError:
            pass

    if "amanhã" in low or "amanha" in low:
        d = hoje + timedelta(days=1)
        return (f"amanhã ({d.strftime('%d/%m')})", d.isoformat(), d.isoformat())
    if "hoje" in low:
        return (f"hoje ({hoje.strftime('%d/%m')})", hoje.isoformat(), hoje.isoformat())
    if "atrasad" in low or "vencid" in low or "em atraso" in low:
        return ("em atraso", "0001-01-01", (hoje - timedelta(days=1)).isoformat())
    if "semana" in low or "7 dias" in low or "sete dias" in low:
        return ("nos próximos 7 dias", hoje.isoformat(), (hoje + timedelta(days=7)).isoformat())
    if "mês" in low or " mes" in low or "mês" in low:
        prox = date(hoje.year + 1, 1, 1) if hoje.month == 12 else date(hoje.year, hoje.month + 1, 1)
        return (f"em {hoje.strftime('%m/%Y')}", hoje.isoformat(), (prox - timedelta(days=1)).isoformat())

    return (None, None, None)


def formatar_resposta_contas(chat_id, text):
    label, ini, fim = _periodo(text)
    if ini:
        contas = bills.listar_periodo(chat_id, ini, fim)
        periodo = label
    else:
        contas = bills.listar(chat_id, incluir_pagas=False)
        periodo = None

    if not contas:
        return f"Você não tem contas a pagar {periodo}. 🎉" if periodo else "Você não tem contas pendentes. 🎉"

    total = sum((c["valor"] or 0) for c in contas)
    titulo = f"💰 Total a pagar {periodo}: {_fmt_valor(total)}" if periodo else \
        f"💰 Total a pagar (todas as pendentes): {_fmt_valor(total)}"
    linhas = [titulo, ""]
    for c in contas:
        linhas.append(f"• #{c['id']} {c['descricao']}: {_fmt_valor(c['valor'])} — vence {_fmt_data(c['vencimento'])}")
    linhas.append("\nMarcar como paga: /pago <número ou nome>.")
    return "\n".join(linhas)


def _strip_json(s):
    """Remove cercas markdown ```json ... ``` que o modelo às vezes coloca."""
    s = s.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    return s


def _normaliza_venc(iso):
    """Data ISO válida no futuro. Se vier no passado (ano omitido), joga p/ o próximo ano."""
    try:
        d = date.fromisoformat(iso)
    except Exception:
        return None
    hoje = date.today()
    if d < hoje:
        try:
            d = d.replace(year=hoje.year + 1) if d.year <= hoje.year else d
        except ValueError:
            pass
        if d < hoje:
            return None
    return d.isoformat()


def extract_bill(text):
    """Usa o modelo p/ extrair {descricao, valor, vencimento} da mensagem. Retorna dict ou None."""
    hoje = date.today().isoformat()
    sys_prompt = (
        f"Hoje é {hoje}. Extraia da mensagem do usuário os dados de UMA conta a pagar. "
        "Responda APENAS um objeto JSON, sem texto extra, com as chaves: "
        '"descricao" (string curta, ex: "Luz"), "valor" (número em reais, ponto decimal, ou null), '
        '"vencimento" (data no formato YYYY-MM-DD; se o ano não for dito, use o próximo vencimento futuro; ou null). '
        'Exemplo: {"descricao":"Luz","valor":100.0,"vencimento":"2026-08-25"}'
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": text},
        ],
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        raw = _strip_json(r.json()["message"]["content"])
        data = json.loads(raw)
    except Exception:
        log.exception("Falha ao extrair conta")
        return None

    desc = (data.get("descricao") or "").strip()
    venc = _normaliza_venc(str(data.get("vencimento") or ""))
    if not desc or not venc:
        return None
    valor = data.get("valor")
    try:
        valor = float(valor) if valor is not None else None
    except (TypeError, ValueError):
        valor = None
    return {"descricao": desc[:100], "valor": valor, "vencimento": venc}


def _fmt_valor(v):
    if v is None:
        return "valor não informado"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_data(iso):
    try:
        return date.fromisoformat(iso).strftime("%d/%m/%Y")
    except Exception:
        return iso


def _valor_falado(v):
    """Valor por extenso p/ o TTS soar natural (evita 'R$' lido letra a letra)."""
    if v is None:
        return "sem valor informado"
    reais = int(v)
    centavos = int(round((v - reais) * 100))
    txt = f"{reais} {'real' if reais == 1 else 'reais'}"
    if centavos:
        txt += f" e {centavos} centavos"
    return txt


def enviar_lembretes():
    """Chamado pelo agendador: avisa contas vencendo (uma vez por conta). Áudio com fallback p/ texto."""
    try:
        hoje_iso = date.today().isoformat()
        for c in bills.vencendo(hoje_iso):
            venc = _fmt_data(c["vencimento"])
            hoje = c["vencimento"] == hoje_iso
            quando_txt = "vence HOJE" if hoje else f"venceu em {venc}"
            quando_falado = "vence hoje" if hoje else f"venceu em {venc}"
            legenda = (
                f"🔔 Lembrete de conta a pagar:\n\n{c['descricao']}: {_fmt_valor(c['valor'])} — {quando_txt}.\n\n"
                f"Quando pagar, me avise: /pago {c['id']}"
            )
            falado = (
                f"Olá! Lembrete de conta a pagar. {c['descricao']}, "
                f"{_valor_falado(c['valor'])}, {quando_falado}."
            )
            enviado = False
            if REMINDER_VOICE and OPENAI_API_KEY:
                audio = tts(falado)
                if audio:
                    try:
                        send_voice(c["chat_id"], audio, caption=legenda)
                        enviado = True
                    except Exception:
                        log.exception("sendVoice falhou; caindo p/ texto")
            if not enviado:
                send_message(c["chat_id"], legenda)
            bills.marcar_lembrete_enviado(c["id"])
    except Exception:
        log.exception("Erro ao enviar lembretes")


def scheduler_loop():
    """Roda em thread separada: a cada 30 min, no horário configurado, dispara os lembretes."""
    log.info("Agendador de lembretes iniciado (hora alvo: %sh, fuso %s).", REMINDER_HOUR, TZ)
    while True:
        try:
            agora = datetime.now(ZoneInfo(TZ))
            if agora.hour >= REMINDER_HOUR:
                enviar_lembretes()
        except Exception:
            log.exception("Erro no agendador")
        time.sleep(1800)


def system_prompt_agora():
    """O modelo não tem relógio próprio — injetamos a data/hora real a cada mensagem."""
    now = datetime.now(ZoneInfo(TZ))
    dia = _DIAS[now.weekday()]
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"AGORA: hoje é {dia}, {now.strftime('%d/%m/%Y')}, e são {now.strftime('%H:%M')} "
        f"(horário de {TZ}). Ao falar de data, dia da semana ou hora, use EXATAMENTE "
        f"esses valores — não recalcule nem mude o dia da semana.\n"
        f"Responda normalmente usando o seu conhecimento — a maioria das perguntas "
        f"(explicações, conceitos, história, ajuda, ideias, etc.) você sabe responder e "
        f"deve responder à vontade. A ÚNICA exceção são dados que mudam em tempo real e "
        f"que não foram fornecidos a você nesta conversa (ex.: previsão do tempo, notícias "
        f"de hoje, cotações, placares ao vivo): apenas nesses casos, diga que não tem essa "
        f"informação atualizada, em vez de inventar. Nunca recuse uma pergunta comum de "
        f"conhecimento geral alegando falta de internet."
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


def transcrever_voz(file_id):
    """Baixa o áudio do Telegram e transcreve via Whisper da OpenAI. Retorna texto ou None."""
    try:
        info = requests.get(f"{TG}/getFile", params={"file_id": file_id}, timeout=30).json()
        file_path = info["result"]["file_path"]
        audio = requests.get(
            f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}", timeout=60
        ).content
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            files={"file": ("audio.ogg", audio, "audio/ogg")},
            data={"model": OPENAI_STT_MODEL, "language": "pt"},
            timeout=120,
        )
        r.raise_for_status()
        return (r.json().get("text") or "").strip()
    except Exception:
        log.exception("Falha ao transcrever áudio")
        return None


def tts(texto):
    """Texto -> áudio Opus (bytes) via OpenAI TTS. Retorna bytes ou None em falha."""
    try:
        r = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": OPENAI_TTS_MODEL,
                "voice": OPENAI_TTS_VOICE,
                "input": texto,
                "response_format": "opus",
            },
            timeout=120,
        )
        r.raise_for_status()
        return r.content
    except Exception:
        log.exception("Falha ao gerar áudio (TTS)")
        return None


def send_voice(chat_id, audio_bytes, caption=None):
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption[:1000]
    r = requests.post(
        f"{TG}/sendVoice",
        data=data,
        files={"voice": ("lembrete.ogg", audio_bytes, "audio/ogg")},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


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

    # Checa acesso ANTES de qualquer processamento (não transcreve áudio de não-autorizado).
    if ALLOWED and str(chat_id) not in ALLOWED:
        log.warning("Chat não autorizado: %s", chat_id)
        send_message(chat_id, f"Acesso não autorizado. Seu chat_id é: {chat_id}")
        return

    text = msg.get("text", "")
    if not text:
        voz = msg.get("voice") or msg.get("audio")
        if voz:
            if not OPENAI_API_KEY:
                send_message(chat_id, "Recebi um áudio, mas a transcrição de voz não está configurada. 🙊")
                return
            send_typing(chat_id)
            text = transcrever_voz(voz["file_id"]) or ""
            if not text:
                send_message(chat_id, "⚠️ Não consegui entender o áudio. Pode repetir ou escrever?")
                return
            send_message(chat_id, f"🎤 Entendi: \"{text}\"")
    if not text:
        return

    cmd = text.strip().lower()

    # Confirmação pendente de uma conta (tem prioridade sobre o resto)
    if chat_id in pending_bill:
        if cmd in _AFIRMATIVO:
            b = pending_bill.pop(chat_id)
            bills.add(chat_id, b["descricao"], b["valor"], b["vencimento"])
            send_message(
                chat_id,
                f"✅ Conta salva: {b['descricao']} — {_fmt_valor(b['valor'])} — "
                f"vence {_fmt_data(b['vencimento'])}.\nVou te lembrar no dia. 🔔",
            )
            return
        if cmd in _NEGATIVO:
            pending_bill.pop(chat_id, None)
            send_message(chat_id, "❌ Ok, não salvei a conta.")
            return
        # Qualquer outra coisa: descarta o pendente e segue o fluxo normal
        pending_bill.pop(chat_id, None)

    if cmd in ("/start", "/help"):
        send_message(
            chat_id,
            "Olá! Eu sou o Hermes 🤖 rodando na sua VPS.\n"
            "Manda sua pergunta que eu respondo.\n\n"
            "/reset — apaga a memória da conversa\n"
            "/buscar <termo> — pesquisa na internet e responde com fontes\n"
            "/contas — lista suas contas a pagar\n"
            "/pago <nº ou nome> — marca uma conta como paga\n"
            "/remover <nº> — remove uma conta\n"
            f"/cidade <nome> — define sua cidade p/ previsão (atual: {chat_city.get(chat_id, DEFAULT_CITY)})\n"
            "/id — mostra seu chat_id\n\n"
            "💡 Pode falar natural ou mandar 🎤 áudio: \"me lembra da conta de luz de 100 reais dia 25/08\".",
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

    # --- Contas a pagar ---
    if cmd.startswith("/pago"):
        arg = text.strip()[len("/pago"):].strip()
        if not arg:
            send_message(chat_id, "Use: /pago <número da conta ou nome>. Veja os números em /contas.")
            return
        if arg.isdigit():
            ok = bills.marcar_pago(chat_id, int(arg))
            send_message(chat_id, "✅ Marcada como paga." if ok else "Não achei uma conta com esse número.")
        else:
            c = bills.marcar_pago_por_descricao(chat_id, arg)
            send_message(chat_id, f"✅ '{c['descricao']}' marcada como paga." if c else f"Não achei conta pendente com '{arg}'.")
        return
    if cmd.startswith("/remover"):
        arg = text.strip()[len("/remover"):].strip()
        if not arg.isdigit():
            send_message(chat_id, "Use: /remover <número da conta>. Veja os números em /contas.")
            return
        ok = bills.remover(chat_id, int(arg))
        send_message(chat_id, "🗑️ Conta removida." if ok else "Não achei uma conta com esse número.")
        return
    if is_bill_list(text):
        send_message(chat_id, formatar_resposta_contas(chat_id, text))
        return
    if is_bill_add(text):
        send_typing(chat_id)
        dados = extract_bill(text)
        if not dados:
            send_message(
                chat_id,
                "Não consegui entender os dados da conta. 😕\n"
                "Tente algo como: \"conta de luz, 100 reais, vence dia 25/08\".",
            )
            return
        pending_bill[chat_id] = dados
        send_message(
            chat_id,
            f"📝 Entendi:\n\n{dados['descricao']} — {_fmt_valor(dados['valor'])} — "
            f"vence {_fmt_data(dados['vencimento'])}.\n\nConfirma? Responda \"sim\" pra salvar ou \"não\" pra cancelar.",
        )
        return

    send_typing(chat_id)
    try:
        ctx = weather_context(chat_id, text) or web_context(text)
    except Exception:
        log.exception("Erro ao montar contexto (clima/web)")
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
    if BILLS_ENABLED:
        bills.init()
        threading.Thread(target=scheduler_loop, daemon=True).start()
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
