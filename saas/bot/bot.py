"""Hermes SaaS — bot multi-tenant (Modelo A: um bot, muitos clientes).

A identidade do cliente vem do TelegramUserId AUTENTICADO (nunca do input). Cada
mensagem resolve o tenant (tenants.resolve) -> UsuarioId, e todo dado de domínio
(contas/compromissos/config) é escopado por esse UsuarioId. O uso (tokens/voz/TTS/
mensagens) é medido em H01UsoMensal e o limite de voz do plano é aplicado antes de
transcrever áudio.
"""
import os
import re
import json
import time
import socket
import logging
import threading
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import requests

# --- Força IPv4 ---------------------------------------------------------------
# Em máquinas com IPv6 quebrado, cada conexão NOVA tenta o IPv6 primeiro e trava
# ~21s no timeout do SYN (3+6+12s no Windows) antes de cair pro IPv4 — o que fazia
# cada chamada ao Telegram levar ~22s. Filtrando o getaddrinfo para IPv4 (quando
# existir) o handshake volta ao normal. Seguro: se não houver IPv4, mantém a lista
# original (ambientes IPv6-only seguem funcionando). Desligue com FORCE_IPV4=0.
if os.environ.get("FORCE_IPV4", "1").lower() not in ("0", "false", "no"):
    _orig_getaddrinfo = socket.getaddrinfo

    def _getaddrinfo_ipv4(*args, **kwargs):
        res = _orig_getaddrinfo(*args, **kwargs)
        v4 = [r for r in res if r[0] == socket.AF_INET]
        return v4 or res

    socket.getaddrinfo = _getaddrinfo_ipv4

# Sessão HTTP reutilizável (keep-alive): evita refazer o handshake TLS a cada
# chamada ao Telegram — economiza uma ida-e-volta por mensagem.
SESSION = requests.Session()

import weather
import websearch
import bills
import reminders
import db
import tenants
import usage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("hermes-bot")

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "hermes3:3b")
# Provedor do "cérebro": "ollama" (local, na VPS) ou "groq" (nuvem, rápido).
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    "Você é o Hermes, um assistente útil e direto. Responda em português do Brasil.",
)
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "12"))  # mensagens (user+assistant) por tenant
REQUEST_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))  # geração em CPU pode demorar
TZ = os.environ.get("TZ", "America/Sao_Paulo")  # fuso usado p/ informar data/hora ao modelo
WEATHER_ENABLED = os.environ.get("WEATHER_ENABLED", "true").lower() != "false"
WEBSEARCH_ENABLED = os.environ.get("WEBSEARCH_ENABLED", "true").lower() != "false"
BILLS_ENABLED = os.environ.get("BILLS_ENABLED", "true").lower() != "false"
REMINDERS_ENABLED = os.environ.get("REMINDERS_ENABLED", "true").lower() != "false"  # compromissos c/ hora
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")  # p/ transcrever áudio (Whisper); vazio = voz off
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "whisper-1")
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "tts-1")  # texto->voz p/ lembretes
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "nova")
REMINDER_VOICE = os.environ.get("REMINDER_VOICE", "true").lower() != "false"  # lembrete em áudio
TIMING = os.environ.get("HERMES_TIMING", "").lower() in ("1", "true", "yes")  # loga tempo por etapa

# Estado em memória, agora escopado por UsuarioId (o tenant), não pelo chat do Telegram.
pending_bill: dict[int, dict] = {}        # {"descricao","valor","vencimento"}
pending_reminder: dict[int, dict] = {}    # {"descricao","quando"}
history: dict[int, list[dict]] = {}       # usuario_id -> list[{"role","content"}]

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

ONBOARD_MSG = (
    "👋 Olá! Eu sou o Hermes, seu assistente pessoal por Telegram.\n\n"
    "Este número ainda não está conectado a nenhuma conta. Para começar:\n"
    "1. Acesse o painel do Hermes e faça login.\n"
    "2. Gere seu código de conexão.\n"
    "3. Volte aqui e envie: /start SEU_CODIGO\n\n"
    "Se precisar do seu identificador de suporte, envie /id."
)


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
    if cand.lower() in {"casa", "breve", "seguida", "que", "geral", "dia", "semana"}:
        return None
    return cand


def weather_context(tenant, text):
    """Se for pergunta de clima, busca dados reais e devolve um bloco de contexto (ou None)."""
    if not WEATHER_ENABLED or not is_weather_question(text):
        return None
    stored = tenant.get("Cidade") or "Jacareí"
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
_BILL_ADD_KW = ["conta de", "conta da", "conta do", "boleto", "fatura", "vence", "a pagar", "pagar"]
# Intenção explícita de CADASTRAR conta/pagamento — dispara mesmo sem número na frase
# (aí o fluxo pede descrição/valor/vencimento que faltarem).
_BILL_ADD_INTENT = [
    "agendar pagamento", "agende pagamento", "agendar um pagamento", "agende um pagamento",
    "agenda um pagamento", "agenda pagamento", "cadastrar conta", "cadastrar uma conta",
    "cadastre uma conta", "cadastra uma conta", "adicionar conta", "adiciona uma conta",
    "anota uma conta", "anotar conta", "nova conta",
]
_BILL_LIST_KW = [
    "minhas contas", "quais contas", "contas a pagar", "o que tenho pra pagar",
    "o que tenho para pagar", "lista de contas", "listar contas", "tenho pra pagar",
    "tenho para pagar", "quais são minhas contas",
]


def is_bill_add(text):
    if not BILLS_ENABLED:
        return False
    low = text.lower()
    if any(p in low for p in _BILL_ADD_INTENT):  # intenção clara → entra e pede o que faltar
        return True
    tem_dinheiro = any(kw in low for kw in _BILL_ADD_KW) or "reais" in low or "r$" in low
    return tem_dinheiro and any(ch.isdigit() for ch in low)


# Compromissos com hora ------------------------------------------------------
_REMINDER_CUE = [
    "me avise", "me avisa", "avise", "avisa", "me lembre", "me lembra", "lembrar", "lembra",
    "reunião", "reuniao", "compromisso", "consulta", "médico", "medico", "dentista",
    "encontro", "ligar", "chamar", "aniversário", "aniversario", "marcar", "agendar", "evento",
]


def _tem_hora(low):
    return bool(re.search(r"\b\d{1,2}\s*h(?:oras|rs)?\b|\b\d{1,2}:\d{2}\b|às\s+\d{1,2}|meio[- ]dia|meia[- ]noite", low))


def _tem_dia(low):
    if any(w in low for w in ["hoje", "amanhã", "amanha", "segunda", "terça", "terca", "quarta",
                              "quinta", "sexta", "sábado", "sabado", "domingo", "dia "]):
        return True
    return bool(re.search(r"\b\d{1,2}[/-]\d{1,2}\b", low))


_REMINDER_NOUN = ["compromisso", "lembrete", "agenda"]
_QUERY_WORD = ["quais", "qual", "o que", "que ", "quantos", "mostra", "mostrar", "lista",
               "listar", "ver ", "tem algum", "tenho algum", "meus", "minha", "quero ver"]


def is_reminder_list(text):
    """Consulta de compromissos (listar), não cadastro."""
    if not REMINDERS_ENABLED:
        return False
    low = text.lower()
    if not any(n in low for n in _REMINDER_NOUN):
        return False
    if _tem_hora(low):  # tem hora específica -> é cadastro, não consulta
        return False
    return any(q in low for q in _QUERY_WORD) or low.strip().endswith("?")


def is_reminder_add(text):
    if not REMINDERS_ENABLED:
        return False
    low = text.lower()
    if is_reminder_list(text):  # consulta tem prioridade sobre cadastro
        return False
    if not any(c in low for c in _REMINDER_CUE):
        return False
    return _tem_hora(low) or _tem_dia(low)


def _normaliza_datahora(iso):
    """datetime ISO válido no futuro (naive, hora local). None se inválido ou no passado."""
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return None
    agora = datetime.now(ZoneInfo(TZ)).replace(tzinfo=None)
    if dt < agora:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M")


def extract_reminder(text, usuario_id):
    """Extrai {descricao, quando} de um compromisso. Retorna dict ou None."""
    agora = datetime.now(ZoneInfo(TZ))
    sys_prompt = (
        f"Hoje é {agora.strftime('%Y-%m-%d')} e agora são {agora.strftime('%H:%M')} (fuso {TZ}). "
        "Extraia da mensagem UM compromisso/lembrete. Responda APENAS um JSON, sem texto extra, "
        'com as chaves: "descricao" (string curta do que é) e "quando" (data e hora no formato '
        'YYYY-MM-DDTHH:MM). Se a hora não for dita, use 09:00. Use sempre o próximo horário futuro. '
        'Exemplo: {"descricao":"Reunião com Adriana","quando":"2026-08-11T09:00"}'
    )
    try:
        data = json.loads(_strip_json(llm_chat(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            temperature=0, usuario_id=usuario_id,
        )))
    except Exception:
        log.exception("Falha ao extrair compromisso")
        return None
    desc = (data.get("descricao") or "").strip()
    quando = _normaliza_datahora(str(data.get("quando") or ""))
    if not desc or not quando:
        return None
    return {"descricao": desc[:150], "quando": quando}


def _fmt_datahora(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return iso


def formatar_lista_lembretes(usuario_id, text=None):
    label, ini, fim = _periodo(text) if text else (None, None, None)
    if ini:
        ls = reminders.listar_periodo(usuario_id, ini, fim)
        titulo, vazio = f"🗓️ Seus compromissos {label}:", f"Você não tem compromissos {label}. 🎉"
    else:
        ls = reminders.listar(usuario_id)
        titulo, vazio = "🗓️ Seus próximos compromissos:", "Você não tem compromissos agendados. 🎉"
    if not ls:
        return vazio
    linhas = [titulo]
    for l in ls:
        linhas.append(f"#{l['id']} — {l['descricao']} — {_fmt_datahora(l['quando'])}")
    linhas.append("\nCancelar: /cancelar <número>.")
    return "\n".join(linhas)


def enviar_lembretes_compromissos(agora):
    """Avisa compromissos dentro da antecedência de cada tenant. Áudio (se VozAtiva) + fallback texto."""
    try:
        for l in reminders.due(agora):
            dt = datetime.fromisoformat(l["quando"])
            legenda = f"🔔 Lembrete: {l['descricao']}\n🕒 {dt.strftime('%d/%m')} às {dt.strftime('%H:%M')}"
            falado = f"Lembrete: {l['descricao']}, às {dt.strftime('%H:%M')}."
            destino = l["telegram_user_id"]
            enviado = False
            if REMINDER_VOICE and OPENAI_API_KEY and l["voz_ativa"]:
                audio = tts(falado)
                if audio:
                    try:
                        send_voice(destino, audio, caption=legenda)
                        usage.registrar(l["usuario_id"], caracteres_tts=len(falado))
                        enviado = True
                    except Exception:
                        log.exception("sendVoice (compromisso) falhou; caindo p/ texto")
            if not enviado:
                send_message(destino, legenda)
            reminders.marcar_avisado(l["id"])
    except Exception:
        log.exception("Erro ao enviar compromissos")


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
    hoje = hoje_local()

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
    if "mês" in low or " mes" in low:
        prox = date(hoje.year + 1, 1, 1) if hoje.month == 12 else date(hoje.year, hoje.month + 1, 1)
        return (f"em {hoje.strftime('%m/%Y')}", hoje.isoformat(), (prox - timedelta(days=1)).isoformat())

    return (None, None, None)


def formatar_resposta_contas(usuario_id, text):
    label, ini, fim = _periodo(text)
    if ini:
        contas = bills.listar_periodo(usuario_id, ini, fim)
        periodo = label
    else:
        contas = bills.listar(usuario_id, incluir_pagas=False)
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
    hoje = hoje_local()
    if d < hoje:
        try:
            d = d.replace(year=hoje.year + 1) if d.year <= hoje.year else d
        except ValueError:
            pass
        if d < hoje:
            return None
    return d.isoformat()


def _juntar_pt(itens):
    """Junta itens em PT: 'a' | 'a e b' | 'a, b e c'."""
    if not itens:
        return ""
    if len(itens) == 1:
        return itens[0]
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def extract_bill(text, usuario_id):
    """Extrai {descricao, valor, vencimento} da mensagem — cada campo pode vir None se o
    usuário não disse. Retorna o dict (com Nones) ou None só se o modelo/JSON falhar.
    Quem chama valida o que falta."""
    hoje = hoje_local().isoformat()
    sys_prompt = (
        f"Hoje é {hoje}. Extraia da mensagem do usuário os dados de UMA conta a pagar. "
        "Responda APENAS um objeto JSON, sem texto extra, com as chaves: "
        '"descricao" (string curta do que é a conta, ex: "Luz", ou null), '
        '"valor" (número em reais com ponto decimal, ou null), '
        '"vencimento" (data YYYY-MM-DD; se o ano não for dito, use o próximo vencimento futuro; ou null). '
        "IMPORTANTE: use null para qualquer dado que o usuário NÃO disse — NÃO invente valor nem data. "
        'Exemplo: {"descricao":"Luz","valor":100.0,"vencimento":"2026-08-25"}'
    )
    try:
        raw = _strip_json(llm_chat(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            temperature=0, usuario_id=usuario_id,
        ))
        data = json.loads(raw)
    except Exception:
        log.exception("Falha ao extrair conta")
        return None

    desc = (data.get("descricao") or "").strip() or None
    venc = _normaliza_venc(str(data.get("vencimento") or ""))
    valor = data.get("valor")
    try:
        valor = float(valor) if valor is not None else None
    except (TypeError, ValueError):
        valor = None
    return {"descricao": desc[:100] if desc else None, "valor": valor, "vencimento": venc}


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
    """Chamado pelo agendador: avisa contas vencendo (uma vez por conta), por tenant.
    Áudio (se VozAtiva) com fallback p/ texto."""
    try:
        hoje_iso = hoje_local().isoformat()
        hora = agora_local().hour
        for c in bills.vencendo(hoje_iso, hora):
            venc = _fmt_data(c["vencimento"])
            eh_hoje = c["vencimento"] == hoje_iso
            quando_txt = "vence HOJE" if eh_hoje else f"venceu em {venc}"
            quando_falado = "vence hoje" if eh_hoje else f"venceu em {venc}"
            legenda = (
                f"🔔 Lembrete de conta a pagar:\n\n{c['descricao']}: {_fmt_valor(c['valor'])} — {quando_txt}.\n\n"
                f"Quando pagar, me avise: /pago {c['id']}"
            )
            falado = (
                f"Olá! Lembrete de conta a pagar. {c['descricao']}, "
                f"{_valor_falado(c['valor'])}, {quando_falado}."
            )
            destino = c["telegram_user_id"]
            enviado = False
            if REMINDER_VOICE and OPENAI_API_KEY and c["voz_ativa"]:
                audio = tts(falado)
                if audio:
                    try:
                        send_voice(destino, audio, caption=legenda)
                        usage.registrar(c["usuario_id"], caracteres_tts=len(falado))
                        enviado = True
                    except Exception:
                        log.exception("sendVoice falhou; caindo p/ texto")
            if not enviado:
                send_message(destino, legenda)
            bills.marcar_lembrete_enviado(c["id"])
    except Exception:
        log.exception("Erro ao enviar lembretes")


def scheduler_loop():
    """Thread: a cada 60s avisa compromissos na hora e contas vencendo (respeitando a
    HoraLembrete/AntecedenciaMin de cada tenant, filtradas no SQL)."""
    log.info("Agendador multi-tenant iniciado (varredura a cada 60s; fuso %s).", TZ)
    while True:
        try:
            agora = datetime.now(ZoneInfo(TZ)).replace(tzinfo=None)
            if REMINDERS_ENABLED:
                enviar_lembretes_compromissos(agora)
            if BILLS_ENABLED:
                enviar_lembretes()
        except Exception:
            log.exception("Erro no agendador")
        time.sleep(60)


def agora_local():
    """Data/hora atual no fuso configurado. NUNCA usar date.today()/datetime.now() (dão UTC no container)."""
    return datetime.now(ZoneInfo(TZ))


def hoje_local():
    return agora_local().date()


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


TG = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def tg(method, **params):
    t0 = time.perf_counter()
    r = SESSION.post(f"{TG}/{method}", json=params, timeout=60)
    r.raise_for_status()
    if TIMING:
        log.info("[t] TG %s: %.0f ms", method, (time.perf_counter() - t0) * 1000)
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
        info = SESSION.get(f"{TG}/getFile", params={"file_id": file_id}, timeout=30).json()
        file_path = info["result"]["file_path"]
        audio = SESSION.get(
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
    r = SESSION.post(
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


def llm_chat(messages, temperature=None, usuario_id=None):
    """Chama o provedor de LLM ativo (Ollama local ou Groq), devolve o TEXTO e — se
    usuario_id for passado — mede os tokens consumidos em H01UsoMensal."""
    t0 = time.perf_counter()
    if LLM_PROVIDER == "groq":
        payload = {"model": GROQ_MODEL, "messages": messages, "stream": False}
        if temperature is not None:
            payload["temperature"] = temperature
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        texto = data["choices"][0]["message"]["content"]
        tokens = int((data.get("usage") or {}).get("total_tokens", 0) or 0)
    else:
        payload = {"model": OLLAMA_MODEL, "messages": messages, "stream": False}
        if temperature is not None:
            payload["options"] = {"temperature": temperature}
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        texto = data["message"]["content"]
        tokens = int(data.get("prompt_eval_count", 0) or 0) + int(data.get("eval_count", 0) or 0)

    if TIMING:
        log.info("[t] LLM %s: %.0f ms, %d tokens", LLM_PROVIDER, (time.perf_counter() - t0) * 1000, tokens)
    if usuario_id and tokens:
        usage.registrar(usuario_id, tokens=tokens)
    return texto


def ask_hermes(usuario_id, user_text, extra_context=None):
    msgs = [{"role": "system", "content": system_prompt_agora()}]
    if extra_context:
        msgs.append({"role": "system", "content": extra_context})
    msgs += history.get(usuario_id, [])
    msgs.append({"role": "user", "content": user_text})

    reply = llm_chat(msgs, usuario_id=usuario_id).strip()

    h = history.get(usuario_id, [])
    h.append({"role": "user", "content": user_text})
    h.append({"role": "assistant", "content": reply})
    history[usuario_id] = h[-MAX_HISTORY:]
    return reply


def help_text(tenant):
    cidade = tenant.get("Cidade") or "não definida"
    return (
        "Olá! Eu sou o Hermes 🤖 seu assistente pessoal.\n"
        "Manda sua pergunta que eu respondo (texto ou 🎤 áudio).\n\n"
        "/reset — apaga a memória da conversa\n"
        "/buscar <termo> — pesquisa na internet e responde com fontes\n"
        "/contas — lista suas contas a pagar\n"
        "/pago <nº ou nome> — marca uma conta como paga\n"
        "/remover <nº> — remove uma conta\n"
        "/lembretes — lista seus compromissos agendados\n"
        "/cancelar <nº> — cancela um lembrete\n"
        f"/cidade <nome> — define sua cidade p/ previsão (atual: {cidade})\n"
        "/id — mostra seu identificador de suporte\n\n"
        "💡 Fale natural ou por 🎤 áudio:\n"
        "• \"me lembra da conta de luz de 100 reais dia 25/08\"\n"
        "• \"me avise amanhã às 9h da reunião com a Adriana\""
    )


_MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}


def handle(update):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    frm = msg.get("from") or {}
    username = frm.get("username")

    text = msg.get("text", "")
    voz = msg.get("voice") or msg.get("audio")
    low = text.strip().lower()

    # /id — funciona para qualquer um (suporte/diagnóstico), mesmo sem vínculo.
    if low == "/id":
        send_message(chat_id, f"Seu identificador de suporte é: {chat_id}")
        return

    # /start <token> — onboarding: vincula este Telegram a uma conta.
    if low.startswith("/start"):
        arg = text.strip()[len("/start"):].strip()
        if arg:
            ok, m = tenants.vincular(arg, chat_id, username)
            send_message(chat_id, m)
            return
        # /start sem token: se já vinculado, mostra ajuda; senão, orienta o onboarding.
        t = tenants.resolve(chat_id)
        send_message(chat_id, help_text(t) if t else ONBOARD_MSG)
        return

    # Resolve o tenant a partir do Telegram autenticado. Sem vínculo -> onboarding.
    tenant = tenants.resolve(chat_id)
    if not tenant:
        send_message(chat_id, ONBOARD_MSG)
        return
    usuario_id = tenant["usuario_id"]

    # --- Áudio: aplica o limite de voz do plano ANTES de transcrever (não gasta cota à toa) ---
    if not text and voz:
        if not OPENAI_API_KEY:
            send_message(chat_id, "Recebi um áudio, mas a transcrição de voz não está configurada. 🙊")
            return
        dur = int(voz.get("duration") or 0)
        permitido, restante = usage.voz_permitida(tenant, dur)
        if not permitido:
            send_message(
                chat_id,
                "🎙️ Você atingiu o limite de voz do seu plano neste mês "
                f"(restam {usage._fmt_min(restante)}). Pode continuar normalmente por TEXTO — "
                "a cota de voz reinicia no dia 1º.",
            )
            return
        send_typing(chat_id)
        text = transcrever_voz(voz["file_id"]) or ""
        usage.registrar(usuario_id, segundos_voz=dur)  # mede o áudio recebido (Whisper)
        if not text:
            send_message(chat_id, "⚠️ Não consegui entender o áudio. Pode repetir ou escrever?")
            return
        # No cadastro de conta/compromisso não mostra o eco — a confirmação (📝 Entendi) já resume os dados.
        if not is_bill_add(text) and not is_reminder_add(text):
            send_message(chat_id, f"🎤 Entendi: \"{text}\"")
    if not text:
        return

    usage.registrar(usuario_id, mensagens=1)  # conta a mensagem processada
    cmd = text.strip().lower()

    # Confirmação pendente de uma conta (tem prioridade sobre o resto)
    if usuario_id in pending_bill:
        if cmd in _AFIRMATIVO:
            b = pending_bill.pop(usuario_id)
            bills.add(usuario_id, b["descricao"], b["valor"], b["vencimento"])
            send_message(
                chat_id,
                "✅ Conta salva.\nVou te lembrar no dia. 🔔",
            )
            return
        if cmd in _NEGATIVO:
            pending_bill.pop(usuario_id, None)
            send_message(chat_id, "❌ Ok, não salvei a conta.")
            return
        pending_bill.pop(usuario_id, None)

    # Confirmação pendente de um compromisso
    if usuario_id in pending_reminder:
        if cmd in _AFIRMATIVO:
            r = pending_reminder.pop(usuario_id)
            reminders.add(usuario_id, r["descricao"], r["quando"])
            antecedencia = tenant.get("AntecedenciaMin", 15)
            send_message(
                chat_id,
                f"✅ Lembrete agendado.\nTe aviso cerca de {antecedencia} min antes. 🔔",
            )
            return
        if cmd in _NEGATIVO:
            pending_reminder.pop(usuario_id, None)
            send_message(chat_id, "❌ Ok, não agendei.")
            return
        pending_reminder.pop(usuario_id, None)

    if cmd in ("/help", "/ajuda"):
        send_message(chat_id, help_text(tenant))
        return
    if cmd == "/reset":
        history.pop(usuario_id, None)
        send_message(chat_id, "Memória da conversa apagada. 🧹")
        return
    if cmd.startswith("/cidade"):
        nome = text.strip()[len("/cidade"):].strip()
        if not nome:
            send_message(chat_id, f"Sua cidade atual é: {tenant.get('Cidade')}.\nUse: /cidade São Paulo")
            return
        try:
            g = weather.geocode(nome)
        except Exception:
            g = None
        if not g:
            send_message(chat_id, f"Não encontrei a cidade '{nome}'. Tente o nome completo, ex: /cidade Campos do Jordão")
            return
        cidade = g.get("name", nome)
        tenants.set_cidade(usuario_id, cidade)
        tenants.invalidate(chat_id)  # próxima mensagem relê a config atualizada
        local = cidade + (f", {g.get('admin1')}" if g.get("admin1") else "")
        send_message(chat_id, f"Cidade definida: {local}. ✅ Agora é só perguntar a previsão.")
        return

    # --- Contas a pagar ---
    if cmd.startswith("/pago"):
        arg = text.strip()[len("/pago"):].strip()
        if not arg:
            send_message(chat_id, "Use: /pago <número da conta ou nome>. Veja os números em /contas.")
            return
        if arg.isdigit():
            ok = bills.marcar_pago(usuario_id, int(arg))
            send_message(chat_id, "✅ Marcada como paga." if ok else "Não achei uma conta com esse número.")
        else:
            c = bills.marcar_pago_por_descricao(usuario_id, arg)
            send_message(chat_id, f"✅ '{c['descricao']}' marcada como paga." if c else f"Não achei conta pendente com '{arg}'.")
        return
    if cmd.startswith("/remover"):
        arg = text.strip()[len("/remover"):].strip()
        if not arg.isdigit():
            send_message(chat_id, "Use: /remover <número da conta>. Veja os números em /contas.")
            return
        ok = bills.remover(usuario_id, int(arg))
        send_message(chat_id, "🗑️ Conta removida." if ok else "Não achei uma conta com esse número.")
        return
    if is_bill_list(text):
        send_message(chat_id, formatar_resposta_contas(usuario_id, text))
        return
    if is_bill_add(text):
        send_typing(chat_id)
        dados = extract_bill(text, usuario_id)
        if dados is None:
            send_message(
                chat_id,
                "Não consegui entender os dados da conta. 😕\n"
                "Tente algo como: \"conta de luz de 100 reais, vence dia 25/08\".",
            )
            return
        # Exige os três: descrição, valor e vencimento. Faltando qualquer um, pede e NÃO cadastra.
        faltando = []
        if not dados["descricao"]:
            faltando.append("o que é a conta (descrição)")
        if dados["valor"] is None:
            faltando.append("o valor")
        if not dados["vencimento"]:
            faltando.append("a data de vencimento")
        if faltando:
            send_message(
                chat_id,
                "Pra cadastrar a conta eu preciso de " + _juntar_pt(faltando) + ". "
                "Pode me mandar completo?\n"
                "Ex.: \"conta de luz de 100 reais, vence dia 25/08\".",
            )
            return
        pending_reminder.pop(usuario_id, None)
        pending_bill[usuario_id] = dados
        send_message(
            chat_id,
            f"📝 Entendi:\n\n{dados['descricao']} — {_fmt_valor(dados['valor'])} — "
            f"vence {_fmt_data(dados['vencimento'])}.\n\nConfirma? Responda \"sim\" pra salvar ou \"não\" pra cancelar.",
        )
        return

    # --- Compromissos com hora ---
    if cmd == "/lembretes":
        send_message(chat_id, formatar_lista_lembretes(usuario_id))
        return
    if cmd.startswith("/cancelar"):
        arg = text.strip()[len("/cancelar"):].strip()
        if not arg.isdigit():
            send_message(chat_id, "Use: /cancelar <número do lembrete>. Veja em /lembretes.")
            return
        ok = reminders.remover(usuario_id, int(arg))
        send_message(chat_id, "🗑️ Lembrete cancelado." if ok else "Não achei um lembrete com esse número.")
        return
    if is_reminder_list(text):
        send_message(chat_id, formatar_lista_lembretes(usuario_id, text))
        return
    if is_reminder_add(text):
        send_typing(chat_id)
        dados = extract_reminder(text, usuario_id)
        if not dados:
            send_message(
                chat_id,
                "Não consegui entender o compromisso. 😕\n"
                "Tente algo como: \"me avise amanhã às 9h da reunião com a Adriana\".",
            )
            return
        pending_bill.pop(usuario_id, None)
        pending_reminder[usuario_id] = dados
        send_message(
            chat_id,
            f"📝 Entendi:\n\n{dados['descricao']}\n🕒 {_fmt_datahora(dados['quando'])}\n\n"
            f"Confirma? Responda \"sim\" pra agendar ou \"não\" pra cancelar.",
        )
        return

    send_typing(chat_id)
    try:
        ctx = weather_context(tenant, text) or web_context(text)
    except Exception:
        log.exception("Erro ao montar contexto (clima/web)")
        ctx = None
    try:
        reply = ask_hermes(usuario_id, text, extra_context=ctx)
    except Exception as e:
        log.exception("Erro ao consultar Hermes")
        send_message(chat_id, f"⚠️ Erro ao gerar resposta: {e}")
        return
    send_message(chat_id, reply)


def main():
    db.ping()  # falha rápido se o MySQL não estiver acessível
    if LLM_PROVIDER == "groq":
        log.info("Cérebro: GROQ (nuvem), modelo %s.", GROQ_MODEL)
    else:
        log.info("Cérebro: OLLAMA (local), modelo %s.", OLLAMA_MODEL)
        ensure_model()
    if BILLS_ENABLED or REMINDERS_ENABLED:
        threading.Thread(target=scheduler_loop, daemon=True).start()
    log.info("Bot SaaS iniciado. Long polling...")
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
                handle(update)
            except Exception:
                log.exception("Erro ao tratar update")
            if TIMING:
                log.info("[t] update total: %.0f ms", (time.perf_counter() - t0) * 1000)


if __name__ == "__main__":
    main()
