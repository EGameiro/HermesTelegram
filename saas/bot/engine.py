"""Núcleo agnóstico de canal do Hermes.

Recebe uma mensagem já normalizada (`Inbound`) + o transporte do canal (`Sender`),
resolve o tenant pela identidade do canal e executa a intenção (contas, compromissos,
clima, busca ou conversa). Nada aqui conhece o canal concreto — a resposta sai pelo
`MsgContext`, e o agendador entrega pelo sender registrado de cada canal.
"""
import re
import json
import time
import logging
import calendar
import threading
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import config
import llm
import voice
import weather
import websearch
import bills
import reminders
import tenants
import usage
import channels.base as channels

log = logging.getLogger("hermes.engine")

from config import agora_local, hoje_local

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
         "sexta-feira", "sábado", "domingo"]

# Frases que indicam pedido de busca na web (além do comando /buscar).
_WEB_KW = [
    "na internet", "na web", "no google", "pesquise", "pesquisa na", "pesquisar na",
    "notícia", "noticia", "novidades sobre", "últimas notícias", "ultimas noticias",
    "cotação", "cotacao", "o que estão falando", "o que estao falando", "acesse o site",
]

# Palavras que indicam pergunta sobre clima/tempo (evita o bare "tempo").
_WEATHER_KW = [
    "previsão", "previsao", "clima", "chuva", "chover", "chovendo", "choveu",
    "temperatura", "graus", "ensolarad", "nublad", "umidade", "faz frio", "faz calor",
    "tá frio", "ta frio", "tá calor", "ta calor", "está frio", "está calor",
    "do tempo", "tempo em", "tempo hoje", "tempo amanhã", "tempo amanha",
    "tempo essa", "tempo nessa", "tempo esta", "tempo nesta",
]


def onboard_msg(canal):
    return (
        "👋 Olá! Eu sou o Hermes, seu assistente pessoal.\n\n"
        "Este número ainda não está conectado a nenhuma conta. Para começar:\n"
        "1. Acesse o painel do Hermes e faça login.\n"
        "2. Gere seu código de conexão.\n"
        "3. Volte aqui e envie o código (só o código).\n\n"
        "Se precisar do seu identificador de suporte, envie /id."
    )


# Um "código" de vínculo digitado direto (sem /start): 1 palavra alfanumérica curta.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{6,64}$")


def _token_candidato(text):
    t = (text or "").strip()
    return t if _TOKEN_RE.match(t) else None


# ---------------------------------------------------------------------------
# Clima / Web
# ---------------------------------------------------------------------------
def is_weather_question(text):
    t = text.lower()
    return any(kw in t for kw in _WEATHER_KW)


def extract_city(text):
    """Tenta achar a cidade citada após 'em/para/pra/no/na'. O Open-Meteo valida depois."""
    m = re.search(
        r"\b(?:em|para|pra|no|na)\s+([A-Za-zÀ-ÿ][\wÀ-ÿ'\.]+(?:[\s\-][A-Za-zÀ-ÿ][\wÀ-ÿ'\.]+){0,3})",
        text, re.IGNORECASE,
    )
    if not m:
        return None
    cand = m.group(1).strip(" ?.!,").rstrip(".")
    if cand.lower() in {"casa", "breve", "seguida", "que", "geral", "dia", "semana"}:
        return None
    return cand


def weather_context(tenant, text):
    """Se for pergunta de clima, busca dados reais e devolve um bloco de contexto (ou None)."""
    if not config.WEATHER_ENABLED or not is_weather_question(text):
        return None
    stored = tenant.get("Cidade") or "Jacareí"
    cidade = extract_city(text) or stored
    txt, err = weather.forecast_text(cidade)
    if err and cidade != stored:
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
    if not config.WEBSEARCH_ENABLED:
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
# Contas a pagar — detecção de intenção
# ---------------------------------------------------------------------------
_BILL_ADD_KW = ["conta de", "conta da", "conta do", "boleto", "fatura", "vence", "a pagar", "pagar"]
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

_BILL_RECURRING_RE = re.compile(
    r"\bpor\s+\d+\s+(?:mes(?:es)?|m[êe]s)\b"
    r"|\b\d+\s+contas?\b"
    r"|\bde\s+\d+\s+em\s+\d+\s+(?:mes(?:es)?|m[êe]s)\b"
    r"|\btod[oa]s?\s+(?:os\s+)?(?:mes(?:es)?|m[êe]s)\b"
    r"|\bmensal(?:mente)?\b"
)


def is_bill_recurring(text):
    if not config.BILLS_ENABLED:
        return False
    low = text.lower()
    if not _BILL_RECURRING_RE.search(low):
        return False
    tem_conta = any(n in low for n in ("conta", "boleto", "despesa"))
    tem_valor = "reais" in low or "r$" in low or any(kw in low for kw in _BILL_ADD_KW)
    return (tem_conta or tem_valor) and any(ch.isdigit() for ch in low)


def is_bill_add(text):
    if not config.BILLS_ENABLED:
        return False
    low = text.lower()
    if is_bill_recurring(text):
        return False
    if any(p in low for p in _BILL_ADD_INTENT):
        return True
    tem_dinheiro = any(kw in low for kw in _BILL_ADD_KW) or "reais" in low or "r$" in low
    return tem_dinheiro and any(ch.isdigit() for ch in low)


_BILL_PAY_RE = re.compile(r"\b(paguei|paga|pago|pagas|pagos|quitei|quitar|quitad[ao]|baixei|baixa)\b")
_STOP_PAGA = {"com", "para", "pra", "pro", "dia", "das", "dos", "uma", "meu", "minha", "meus",
              "minhas", "que", "esse", "essa", "como", "conta", "contas", "paga", "pago", "pagar",
              "paguei", "quitei", "marca", "marcar", "the"}


def is_bill_pay(text):
    if not config.BILLS_ENABLED:
        return False
    low = text.lower()
    if not _BILL_PAY_RE.search(low):
        return False
    if any(q in low for q in ("quanto", "quais", "quantas", "quantos")):
        return False
    return True


_BILL_REMOVE_CUE = [
    "cancela", "cancelar", "cancele", "apaga", "apagar", "apague", "remove", "remover", "remova",
    "exclui", "excluir", "exclua", "deleta", "deletar", "delete", "tira ", "tirar",
]


def is_bill_remove(text):
    if not config.BILLS_ENABLED:
        return False
    low = text.lower()
    if not any(c in low for c in _BILL_REMOVE_CUE):
        return False
    return any(n in low for n in ("conta", "boleto", "despesa"))


def is_bill_list(text):
    if not config.BILLS_ENABLED:
        return False
    low = text.lower()
    if low.strip() == "/contas":
        return True
    if any(kw in low for kw in _BILL_LIST_KW):
        return True
    total_cue = "quanto" in low or "total" in low
    money_cue = any(w in low for w in (
        "pagar", "conta", "agendad", "boleto", "despesa", "venc",
        "gasto", "valor", "reais", "r$"))
    if total_cue and money_cue:
        return True
    return False


# ---------------------------------------------------------------------------
# Compromissos com hora — detecção de intenção
# ---------------------------------------------------------------------------
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


_REMINDER_NOUN = ["compromisso", "lembrete", "agenda", "agendamento",
                  "reuni", "encontro", "evento",
                  "consulta", "dentista", "aniversário", "aniversario"]
_QUERY_WORD = ["quais", "qual", "o que", "que ", "quantos", "mostra", "mostrar", "lista",
               "listar", "ver ", "tem algum", "tenho algum", "meus", "minha", "quero ver"]


def is_reminder_list(text):
    if not config.REMINDERS_ENABLED:
        return False
    low = text.lower()
    if not any(n in low for n in _REMINDER_NOUN):
        return False
    if _tem_hora(low):
        return False
    return any(q in low for q in _QUERY_WORD) or low.strip().endswith("?")


def is_reminder_add(text):
    if not config.REMINDERS_ENABLED:
        return False
    low = text.lower()
    if is_reminder_list(text):
        return False
    if is_reminder_cancel(text):
        return False
    if is_reminder_recurring(text):
        return False
    if not any(c in low for c in _REMINDER_CUE):
        return False
    return _tem_hora(low) or _tem_dia(low)


_REMINDER_CANCEL_CUE = [
    "cancela", "cancelar", "cancele", "desmarca", "desmarcar", "desmarque",
    "apaga", "apagar", "apague", "remove", "remover", "remova",
    "exclui", "excluir", "exclua", "tira ", "tirar",
]
_STOP_CANCEL = {"com", "para", "pra", "pro", "dia", "das", "dos", "uma", "meu", "minha",
                "meus", "minhas", "que", "esse", "essa", "este", "esta", "the", "compromisso",
                "reuniao", "reunião", "lembrete", "agenda", "agendamento"}


def is_reminder_cancel(text):
    if not config.REMINDERS_ENABLED:
        return False
    low = text.lower()
    if not any(c in low for c in _REMINDER_CANCEL_CUE):
        return False
    return any(n in low for n in _REMINDER_NOUN)


_RECURRING_RE = re.compile(
    r"de\s+\d+\s+em\s+\d+"
    r"|a\s+cada\s+\d+"
    r"|\bde\s+hora\s+em\s+hora\b"
    r"|\btod[oa]s?\s+(?:os\s+|as\s+)?(?:dias?|horas?|semanas?|mes(?:es)?|m[êe]s)\b"
    r"|\bdiariamente\b|\bsemanal(?:mente)?\b|\bmensal(?:mente)?\b"
    r"|\bpor\s+\d+\s+(?:dias?|vezes|semanas?)\b"
    r"|\d+\s*x\s+(?:ao|por)\s+dia"
)


def is_reminder_recurring(text):
    if not config.REMINDERS_ENABLED:
        return False
    low = text.lower()
    if not _RECURRING_RE.search(low):
        return False
    if any(w in low for w in ("conta", "boleto", "pagar", "r$", "reais")):
        return False
    return any(c in low for c in _REMINDER_CUE) or any(n in low for n in _REMINDER_NOUN) or _tem_hora(low)


# ---------------------------------------------------------------------------
# Extração (LLM) e geração
# ---------------------------------------------------------------------------
def _strip_json(s):
    s = s.strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    return s


def _normaliza_datahora(iso):
    try:
        dt = datetime.fromisoformat(iso)
    except Exception:
        return None
    agora = datetime.now(ZoneInfo(config.TZ)).replace(tzinfo=None)
    if dt < agora:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M")


def extract_reminder(text, usuario_id):
    agora = datetime.now(ZoneInfo(config.TZ))
    sys_prompt = (
        f"Hoje é {agora.strftime('%Y-%m-%d')} e agora são {agora.strftime('%H:%M')} (fuso {config.TZ}). "
        "Extraia da mensagem UM compromisso/lembrete. Responda APENAS um JSON, sem texto extra, com as chaves: "
        '"descricao" (string curta do que é), '
        '"quando" (data e hora do COMPROMISSO no formato YYYY-MM-DDTHH:MM) e '
        '"avisar_em" (data e hora em que o usuário quer RECEBER o lembrete, mesmo formato, '
        "ou null se ele NÃO pedir um horário de aviso específico). "
        "Se a hora do compromisso não for dita, use 09:00. Se o usuário der só a HORA do aviso "
        "(ex.: 'me avise às 9h'), use a MESMA data do compromisso. Use sempre horários futuros. "
        'Ex. com aviso: {"descricao":"Reunião com Marcelo","quando":"2026-08-25T10:00","avisar_em":"2026-08-25T09:00"}. '
        'Ex. sem aviso: {"descricao":"Dentista","quando":"2026-08-21T14:30","avisar_em":null}'
    )
    try:
        data = json.loads(_strip_json(llm.llm_chat(
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
    avisar_raw = data.get("avisar_em")
    avisar_em = _normaliza_datahora(str(avisar_raw)) if avisar_raw else None
    return {"descricao": desc[:150], "quando": quando, "avisar_em": avisar_em}


_MAX_OCORRENCIAS = 30


def extract_recurring_reminder(text, usuario_id):
    agora = datetime.now(ZoneInfo(config.TZ))
    hoje = agora.strftime("%Y-%m-%d")
    sys_prompt = (
        f"Hoje é {hoje} e agora são {agora.strftime('%H:%M')} (fuso {config.TZ}). "
        "Extraia um compromisso/lembrete RECORRENTE (que se repete). Responda APENAS um JSON, "
        "sem texto extra, com as chaves: "
        '"descricao" (string curta do que é), '
        '"inicio" (data e hora da PRIMEIRA ocorrência, formato YYYY-MM-DDTHH:MM), '
        '"intervalo_horas" (de quantas em quantas HORAS repete: "de 8 em 8 horas"=8, '
        '"todo dia"/"diariamente"=24, "toda semana"=168, "de hora em hora"=1), '
        '"dias" (por quantos DIAS dura no total, ou null) e '
        '"ocorrencias" (por quantas VEZES repete, ou null). '
        "Se a hora não for dita, use 08:00. Use sempre datas de hoje em diante. "
        'Ex.: {"descricao":"Tomar remédio","inicio":"' + hoje + 'T10:00",'
        '"intervalo_horas":8,"dias":5,"ocorrencias":null}'
    )
    try:
        data = json.loads(_strip_json(llm.llm_chat(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            temperature=0, usuario_id=usuario_id,
        )))
    except Exception:
        log.exception("Falha ao extrair compromisso recorrente")
        return None
    desc = (data.get("descricao") or "").strip()
    inicio = str(data.get("inicio") or "")
    try:
        intervalo = int(data.get("intervalo_horas") or 0)
    except (TypeError, ValueError):
        intervalo = 0
    if not desc or not inicio or intervalo < 1:
        return None
    return {
        "descricao": desc[:150],
        "inicio": inicio,
        "intervalo_horas": intervalo,
        "dias": data.get("dias"),
        "ocorrencias": data.get("ocorrencias"),
    }


def _gerar_ocorrencias(dados):
    try:
        inicio = datetime.fromisoformat(dados["inicio"])
    except Exception:
        return []
    intervalo = max(1, int(dados["intervalo_horas"]))

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    count = _int(dados.get("ocorrencias"))
    if count <= 0 and dados.get("dias"):
        count = _int(dados["dias"]) * 24 // intervalo
    if count <= 0:
        count = 1
    count = min(count, _MAX_OCORRENCIAS)

    agora = datetime.now(ZoneInfo(config.TZ)).replace(tzinfo=None)
    ocorrencias = []
    for i in range(count):
        occ = inicio + timedelta(hours=intervalo * i)
        if occ >= agora:
            ocorrencias.append(occ.strftime("%Y-%m-%dT%H:%M"))
    return ocorrencias


def _normaliza_venc(iso):
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


def extract_bill(text, usuario_id):
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
        raw = _strip_json(llm.llm_chat(
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


def extract_recurring_bill(text, usuario_id):
    hoje = hoje_local().isoformat()
    sys_prompt = (
        f"Hoje é {hoje}. Extraia uma conta a pagar RECORRENTE (mensal). Responda APENAS um JSON, "
        "sem texto extra, com as chaves: "
        '"descricao" (string curta, ex.: "Condomínio"), '
        '"valor" (número em reais com ponto decimal, ex.: 600.00), '
        '"dia_vencimento" (dia do mês do vencimento, 1 a 31), '
        '"meses" (por quantos MESES/quantas contas repetir; "5 contas"=5, "por 12 meses"=12; '
        "se não for dito, use 12) e "
        '"intervalo_meses" (de quantos em quantos meses; "todo mês"=1, "de 2 em 2 meses"=2; padrão 1). '
        'Ex.: {"descricao":"Condomínio","valor":600.00,"dia_vencimento":15,"meses":12,"intervalo_meses":1}'
    )
    try:
        data = json.loads(_strip_json(llm.llm_chat(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": text}],
            temperature=0, usuario_id=usuario_id,
        )))
    except Exception:
        log.exception("Falha ao extrair conta recorrente")
        return None

    def _int(v, padrao=0):
        try:
            return int(v)
        except (TypeError, ValueError):
            return padrao

    desc = (data.get("descricao") or "").strip()
    try:
        valor = float(data.get("valor")) if data.get("valor") is not None else None
    except (TypeError, ValueError):
        valor = None
    dia = _int(data.get("dia_vencimento"))
    if not desc or valor is None or not (1 <= dia <= 31):
        return None
    return {
        "descricao": desc[:100],
        "valor": valor,
        "dia_vencimento": dia,
        "meses": max(1, _int(data.get("meses"), 12)),
        "intervalo_meses": max(1, _int(data.get("intervalo_meses"), 1)),
    }


def _add_mes(ano, mes, n):
    idx = (ano * 12 + (mes - 1)) + n
    return idx // 12, idx % 12 + 1


def _data_venc(ano, mes, dia):
    ultimo = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, min(dia, ultimo))


def _gerar_vencimentos(dados):
    dia = dados["dia_vencimento"]
    intervalo = max(1, dados["intervalo_meses"])
    count = min(max(1, dados["meses"]), _MAX_OCORRENCIAS)
    hoje = hoje_local()
    ano, mes = hoje.year, hoje.month
    if _data_venc(ano, mes, dia) < hoje:
        ano, mes = _add_mes(ano, mes, 1)
    return [_data_venc(*_add_mes(ano, mes, intervalo * i), dia).isoformat() for i in range(count)]


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------
def _fmt_datahora(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return iso


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
    if v is None:
        return "sem valor informado"
    reais = int(v)
    centavos = int(round((v - reais) * 100))
    txt = f"{reais} {'real' if reais == 1 else 'reais'}"
    if centavos:
        txt += f" e {centavos} centavos"
    return txt


def _juntar_pt(itens):
    if not itens:
        return ""
    if len(itens) == 1:
        return itens[0]
    return ", ".join(itens[:-1]) + " e " + itens[-1]


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


def cancelar_compromisso_por_texto(usuario_id, text):
    ativos = reminders.listar(usuario_id)
    if not ativos:
        return "Você não tem compromissos agendados pra cancelar. 🗓️"
    low = text.lower()

    por_id = {c["id"]: c for c in ativos}
    mid = re.search(r"(?:n[uú]mero|n[º°]|#)\s*(\d+)", low)
    if not mid and not re.search(r"\d{1,2}\s*h|\d{1,2}:\d{2}|dia\s+\d|\d{1,2}[/-]\d|(?:às|as|das)\s+\d", low):
        mid = re.search(r"\b(\d{1,6})\b", low)
    if mid and int(mid.group(1)) in por_id:
        alvo = por_id[int(mid.group(1))]
        reminders.remover(usuario_id, alvo["id"])
        return f"🗑️ Compromisso cancelado: {alvo['descricao']} — {_fmt_datahora(alvo['quando'])}."

    _, ini, fim = _periodo(text)
    candidatos = [c for c in ativos if ini <= (c["quando"] or "")[:10] <= fim] if ini else ativos
    if not candidatos:
        candidatos = ativos

    def _score(c):
        palavras = [w for w in re.findall(r"[a-zà-ÿ0-9]+", (c["descricao"] or "").lower())
                    if len(w) >= 3 and w not in _STOP_CANCEL]
        return sum(1 for w in palavras if w in low)

    com_match = sorted((c for c in candidatos if _score(c) > 0), key=_score, reverse=True)
    alvo = None
    if len(com_match) == 1:
        alvo = com_match[0]
    elif len(com_match) >= 2 and _score(com_match[0]) > _score(com_match[1]):
        alvo = com_match[0]
    elif not com_match and ini and len(candidatos) == 1:
        alvo = candidatos[0]

    if alvo:
        reminders.remover(usuario_id, alvo["id"])
        return f"🗑️ Compromisso cancelado: {alvo['descricao']} — {_fmt_datahora(alvo['quando'])}."

    linhas = ["Qual compromisso você quer cancelar? Responda com /cancelar <número>:"]
    for c in candidatos:
        linhas.append(f"#{c['id']} — {c['descricao']} — {_fmt_datahora(c['quando'])}")
    return "\n".join(linhas)


def marcar_conta_paga_por_texto(usuario_id, text):
    pendentes = bills.listar(usuario_id, incluir_pagas=False)
    if not pendentes:
        return "Você não tem contas pendentes. 🎉"
    low = text.lower()

    por_id = {c["id"]: c for c in pendentes}
    mid = re.search(r"(?:n[uú]mero|n[º°]|#)\s*(\d+)", low)
    if not mid and not re.search(r"\d{1,2}\s*h|\d{1,2}:\d{2}|dia\s+\d|\d{1,2}[/-]\d|(?:às|as|das)\s+\d", low):
        mid = re.search(r"\b(\d{1,6})\b", low)
    if mid and int(mid.group(1)) in por_id:
        c = por_id[int(mid.group(1))]
        bills.marcar_pago(usuario_id, c["id"])
        return f"✅ Conta paga: {c['descricao']} — {_fmt_valor(c['valor'])}."

    def _score(c):
        pal = [w for w in re.findall(r"[a-zà-ÿ0-9]+", (c["descricao"] or "").lower())
               if len(w) >= 3 and w not in _STOP_PAGA]
        return sum(1 for w in pal if w in low)

    cm = sorted((c for c in pendentes if _score(c) > 0), key=_score, reverse=True)
    alvo = None
    if len(cm) == 1:
        alvo = cm[0]
    elif len(cm) >= 2 and _score(cm[0]) > _score(cm[1]):
        alvo = cm[0]
    if alvo:
        bills.marcar_pago(usuario_id, alvo["id"])
        return f"✅ Conta paga: {alvo['descricao']} — {_fmt_valor(alvo['valor'])}."

    linhas = ["Qual conta você quer marcar como paga? Responda com /pago <número>:"]
    for c in pendentes:
        linhas.append(f"#{c['id']} — {c['descricao']}: {_fmt_valor(c['valor'])} — vence {_fmt_data(c['vencimento'])}")
    return "\n".join(linhas)


def remover_conta_por_texto(usuario_id, text):
    pendentes = bills.listar(usuario_id, incluir_pagas=False)
    if not pendentes:
        return "Você não tem contas pendentes pra excluir. 🎉"
    low = text.lower()

    por_id = {c["id"]: c for c in pendentes}
    mid = re.search(r"(?:n[uú]mero|n[º°]|#)\s*(\d+)", low)
    if not mid and not re.search(r"\d{1,2}\s*h|\d{1,2}:\d{2}|dia\s+\d|\d{1,2}[/-]\d|(?:às|as|das)\s+\d", low):
        mid = re.search(r"\b(\d{1,6})\b", low)
    if mid and int(mid.group(1)) in por_id:
        c = por_id[int(mid.group(1))]
        bills.remover(usuario_id, c["id"])
        return f"🗑️ Conta excluída: {c['descricao']} — {_fmt_valor(c['valor'])}."

    def _score(c):
        pal = [w for w in re.findall(r"[a-zà-ÿ0-9]+", (c["descricao"] or "").lower())
               if len(w) >= 3 and w not in _STOP_PAGA]
        return sum(1 for w in pal if w in low)

    cm = sorted((c for c in pendentes if _score(c) > 0), key=_score, reverse=True)
    alvo = None
    if len(cm) == 1:
        alvo = cm[0]
    elif len(cm) >= 2 and _score(cm[0]) > _score(cm[1]):
        alvo = cm[0]
    if alvo:
        bills.remover(usuario_id, alvo["id"])
        return f"🗑️ Conta excluída: {alvo['descricao']} — {_fmt_valor(alvo['valor'])}."

    linhas = ["Qual conta você quer excluir? Responda com /remover <número>:"]
    for c in pendentes:
        linhas.append(f"#{c['id']} — {c['descricao']}: {_fmt_valor(c['valor'])} — vence {_fmt_data(c['vencimento'])}")
    return "\n".join(linhas)


def _slots_compromissos(ctx, usuario_id, tenant):
    """Vagas restantes de compromissos EM ABERTO. 0 = cheio (já avisa o usuário)."""
    limite = int(tenant.get("LimiteCompromissos", 100))
    livres = limite - reminders.contar_abertos(usuario_id)
    if livres <= 0:
        ctx.reply(
            f"⚠️ Você atingiu o limite de {limite} compromissos em aberto. "
            "Conclua ou cancele alguns (veja em /lembretes) e tente de novo.")
        return 0
    return livres


def _slots_contas(ctx, usuario_id, tenant):
    """Vagas restantes de contas (pagas ou não). 0 = cheio (já avisa o usuário)."""
    limite = int(tenant.get("LimiteContas", 300))
    livres = limite - bills.contar(usuario_id)
    if livres <= 0:
        ctx.reply(
            f"⚠️ Você atingiu o limite de {limite} contas cadastradas. "
            "Exclua algumas (veja em /contas) e tente de novo.")
        return 0
    return livres


def help_text(tenant):
    cidade = (tenant or {}).get("Cidade") or "não definida"
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


# ---------------------------------------------------------------------------
# Agendador (entrega multi-canal via registro de senders)
# ---------------------------------------------------------------------------
def _entregar(canal, identificador, legenda, falado, voz_ativa, usuario_id):
    """Entrega um lembrete no canal do tenant: áudio (se VozAtiva) com fallback p/ texto."""
    sender = channels.sender_for(canal)
    if sender is None:
        log.warning("Sem sender registrado p/ canal %s; lembrete não entregue.", canal)
        return
    enviado = False
    if config.REMINDER_VOICE and config.OPENAI_API_KEY and voz_ativa:
        audio = voice.tts(falado)
        if audio:
            try:
                if sender.send_voice(identificador, audio, caption=legenda):
                    usage.registrar(usuario_id, caracteres_tts=len(falado))
                    enviado = True
            except Exception:
                log.exception("send_voice falhou; caindo p/ texto")
    if not enviado:
        sender.send_text(identificador, legenda)


def _canal_ident(row):
    """Extrai (canal, identificador) do destino de uma linha de due()/vencendo()."""
    ident = row.get("identificador")
    return row.get("canal"), (str(ident) if ident is not None else None)


def enviar_lembretes_compromissos(agora):
    """Avisa compromissos dentro da antecedência de cada tenant."""
    try:
        for l in reminders.due(agora):
            dt = datetime.fromisoformat(l["quando"])
            legenda = f"🔔 Lembrete: {l['descricao']}\n🕒 {dt.strftime('%d/%m')} às {dt.strftime('%H:%M')}"
            falado = f"Lembrete: {l['descricao']}, às {dt.strftime('%H:%M')}."
            canal, identificador = _canal_ident(l)
            if identificador:
                _entregar(canal, identificador, legenda, falado, l["voz_ativa"], l["usuario_id"])
            reminders.marcar_avisado(l["id"])
    except Exception:
        log.exception("Erro ao enviar compromissos")


def enviar_lembretes():
    """Avisa contas vencendo (uma vez por conta), por tenant."""
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
            canal, identificador = _canal_ident(c)
            if identificador:
                _entregar(canal, identificador, legenda, falado, c["voz_ativa"], c["usuario_id"])
            bills.marcar_lembrete_enviado(c["id"])
    except Exception:
        log.exception("Erro ao enviar lembretes")


def scheduler_loop():
    """Thread: a cada 60s avisa compromissos na hora e contas vencendo (por tenant)."""
    log.info("Agendador multi-tenant iniciado (varredura a cada 60s; fuso %s).", config.TZ)
    while True:
        try:
            agora = datetime.now(ZoneInfo(config.TZ)).replace(tzinfo=None)
            if config.REMINDERS_ENABLED:
                enviar_lembretes_compromissos(agora)
            if config.BILLS_ENABLED:
                enviar_lembretes()
        except Exception:
            log.exception("Erro no agendador")
        time.sleep(60)


_MESES_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}


# ---------------------------------------------------------------------------
# Orquestração principal (era o handle() do bot.py)
# ---------------------------------------------------------------------------
def processar(inbound: channels.Inbound, sender: channels.Sender):
    """Processa UMA mensagem já normalizada, respondendo pelo `sender` do canal."""
    identificador = inbound.identificador
    ctx = channels.MsgContext(sender, identificador)
    text = inbound.text or ""
    low = text.strip().lower()

    # /id — funciona para qualquer um (suporte/diagnóstico), mesmo sem vínculo.
    if low == "/id":
        ctx.reply(f"Seu identificador de suporte é: {identificador}")
        return

    # /start <token> — onboarding: vincula este canal a uma conta.
    if low.startswith("/start"):
        arg = text.strip()[len("/start"):].strip()
        if arg:
            ok, m = tenants.vincular(arg, inbound.canal, identificador, inbound.nome)
            ctx.reply(m)
            return
        t = tenants.resolve(inbound.canal, identificador)
        ctx.reply(help_text(t) if t else onboard_msg(inbound.canal))
        return

    # Resolve o tenant pela identidade autenticada do canal.
    tenant = tenants.resolve(inbound.canal, identificador)
    if not tenant:
        # Sem vínculo: aceita o código digitado direto (fluxo natural do WhatsApp).
        tok = _token_candidato(text)
        if tok:
            ok, m = tenants.vincular(tok, inbound.canal, identificador, inbound.nome)
            if ok:
                ctx.reply(m)
                return
        ctx.reply(onboard_msg(inbound.canal))
        return
    ctx.tenant = tenant
    usuario_id = tenant["usuario_id"]

    # --- Áudio: limite de voz ANTES de baixar/transcrever (não gasta cota à toa) ---
    if not text and inbound.voice_ref is not None:
        if not config.OPENAI_API_KEY:
            ctx.reply("Recebi um áudio, mas a transcrição de voz não está configurada. 🙊")
            return
        dur = int(inbound.voice_seg or 0)
        permitido, restante = usage.voz_permitida(tenant, dur)
        if not permitido:
            ctx.reply(
                "🎙️ Você atingiu o limite de voz do seu plano neste mês "
                f"(restam {usage._fmt_min(restante)}). Pode continuar normalmente por TEXTO — "
                "a cota de voz reinicia no dia 1º.")
            return
        ctx.typing()
        baix = sender.baixar_audio(inbound.voice_ref)
        if not baix:
            ctx.reply("⚠️ Não consegui baixar o áudio. Pode escrever?")
            return
        audio_bytes, fname, mime = baix
        text = voice.transcrever(audio_bytes, fname, mime) or ""
        usage.registrar(usuario_id, segundos_voz=dur)  # mede o áudio recebido (Whisper)
        if not text:
            ctx.reply("⚠️ Não consegui entender o áudio. Pode repetir ou escrever?")
            return
    if not text:
        return

    usage.registrar(usuario_id, mensagens=1)
    cmd = text.strip().lower()

    if cmd in ("/help", "/ajuda"):
        ctx.reply(help_text(tenant))
        return
    if cmd == "/reset":
        llm.reset(usuario_id)
        ctx.reply("Memória da conversa apagada. 🧹")
        return
    if cmd.startswith("/cidade"):
        nome = text.strip()[len("/cidade"):].strip()
        if not nome:
            ctx.reply(f"Sua cidade atual é: {tenant.get('Cidade')}.\nUse: /cidade São Paulo")
            return
        try:
            g = weather.geocode(nome)
        except Exception:
            g = None
        if not g:
            ctx.reply(f"Não encontrei a cidade '{nome}'. Tente o nome completo, ex: /cidade Campos do Jordão")
            return
        cidade = g.get("name", nome)
        tenants.set_cidade(usuario_id, cidade)
        tenants.invalidate(inbound.canal, identificador)  # próxima mensagem relê a config
        local = cidade + (f", {g.get('admin1')}" if g.get("admin1") else "")
        ctx.reply(f"Cidade definida: {local}. ✅ Agora é só perguntar a previsão.")
        return

    # --- Contas a pagar ---
    if cmd.startswith("/pago"):
        arg = text.strip()[len("/pago"):].strip()
        if not arg:
            ctx.reply("Use: /pago <número da conta ou nome>. Veja os números em /contas.")
            return
        if arg.isdigit():
            ok = bills.marcar_pago(usuario_id, int(arg))
            ctx.reply("✅ Marcada como paga." if ok else "Não achei uma conta com esse número.")
        else:
            c = bills.marcar_pago_por_descricao(usuario_id, arg)
            ctx.reply(f"✅ '{c['descricao']}' marcada como paga." if c else f"Não achei conta pendente com '{arg}'.")
        return
    if cmd.startswith("/remover"):
        arg = text.strip()[len("/remover"):].strip()
        if not arg.isdigit():
            ctx.reply("Use: /remover <número da conta>. Veja os números em /contas.")
            return
        ok = bills.remover(usuario_id, int(arg))
        ctx.reply("🗑️ Conta removida." if ok else "Não achei uma conta com esse número.")
        return
    if is_bill_remove(text):
        ctx.reply(remover_conta_por_texto(usuario_id, text))
        return
    if is_bill_pay(text):
        ctx.reply(marcar_conta_paga_por_texto(usuario_id, text))
        return
    if is_bill_list(text):
        ctx.reply(formatar_resposta_contas(usuario_id, text))
        return
    if is_bill_recurring(text):
        ctx.typing()
        dados = extract_recurring_bill(text, usuario_id)
        if not dados:
            ctx.reply(
                "Não consegui entender a conta recorrente. 😕\n"
                "Tente algo como: \"conta de condomínio de 600 reais, vencimento todo dia 15, por 12 meses\".")
            return
        vencimentos = _gerar_vencimentos(dados)
        if not vencimentos:
            ctx.reply("Não consegui gerar os vencimentos — confira o dia e a duração.")
            return
        livres = _slots_contas(ctx, usuario_id, tenant)
        if not livres:
            return
        cortou_limite = len(vencimentos) > livres
        vencimentos = vencimentos[:livres]
        for venc in vencimentos:
            bills.add(usuario_id, dados["descricao"], dados["valor"], venc)
        intervalo = dados["intervalo_meses"]
        freq = "todo mês" if intervalo == 1 else f"a cada {intervalo} meses"
        if cortou_limite:
            extra = "\n(criei só até o seu limite de contas)"
        elif len(vencimentos) >= _MAX_OCORRENCIAS:
            extra = f"\n(atingiu o limite de {_MAX_OCORRENCIAS} contas por série)"
        else:
            extra = ""
        ctx.reply(
            f"✅ Criei {len(vencimentos)} contas de \"{dados['descricao']}\" — {_fmt_valor(dados['valor'])}, {freq}.\n"
            f"🗓️ Vencimentos de {_fmt_data(vencimentos[0])} até {_fmt_data(vencimentos[-1])}.\n"
            f"Vou te lembrar em cada vencimento. 🔔{extra}")
        return
    if is_bill_add(text):
        ctx.typing()
        dados = extract_bill(text, usuario_id)
        if dados is None:
            ctx.reply(
                "Não consegui entender os dados da conta. 😕\n"
                "Tente algo como: \"conta de luz de 100 reais, vence dia 25/08\".")
            return
        faltando = []
        if not dados["descricao"]:
            faltando.append("o que é a conta (descrição)")
        if dados["valor"] is None:
            faltando.append("o valor")
        if not dados["vencimento"]:
            faltando.append("a data de vencimento")
        if faltando:
            ctx.reply(
                "Pra cadastrar a conta eu preciso de " + _juntar_pt(faltando) + ". "
                "Pode me mandar completo?\n"
                "Ex.: \"conta de luz de 100 reais, vence dia 25/08\".")
            return
        if not _slots_contas(ctx, usuario_id, tenant):
            return
        bills.add(usuario_id, dados["descricao"], dados["valor"], dados["vencimento"])
        ctx.reply(
            f"✅ Conta salva: {dados['descricao']} — {_fmt_valor(dados['valor'])} — "
            f"vence {_fmt_data(dados['vencimento'])}.\nVou te lembrar no dia. 🔔")
        return

    # --- Compromissos com hora ---
    if cmd == "/lembretes":
        ctx.reply(formatar_lista_lembretes(usuario_id))
        return
    if cmd.startswith("/cancelar"):
        arg = text.strip()[len("/cancelar"):].strip()
        if not arg.isdigit():
            ctx.reply("Use: /cancelar <número do lembrete>. Veja em /lembretes.")
            return
        ok = reminders.remover(usuario_id, int(arg))
        ctx.reply("🗑️ Lembrete cancelado." if ok else "Não achei um lembrete com esse número.")
        return
    if is_reminder_cancel(text):
        ctx.reply(cancelar_compromisso_por_texto(usuario_id, text))
        return
    if is_reminder_list(text):
        ctx.reply(formatar_lista_lembretes(usuario_id, text))
        return
    if is_reminder_recurring(text):
        ctx.typing()
        dados = extract_recurring_reminder(text, usuario_id)
        if not dados:
            ctx.reply(
                "Não consegui entender o compromisso recorrente. 😕\n"
                "Tente algo como: \"tomar remédio de 8 em 8 horas a partir de hoje às 10h por 5 dias\".")
            return
        ocorrencias = _gerar_ocorrencias(dados)
        if not ocorrencias:
            ctx.reply("Não consegui gerar as datas — confira o horário e a duração.")
            return
        livres = _slots_compromissos(ctx, usuario_id, tenant)
        if not livres:
            return
        cortou_limite = len(ocorrencias) > livres
        ocorrencias = ocorrencias[:livres]
        for occ in ocorrencias:
            reminders.add(usuario_id, dados["descricao"], occ, occ)
        intervalo = dados["intervalo_horas"]
        if intervalo == 24:
            freq = "todo dia"
        elif intervalo % 24 == 0:
            freq = f"a cada {intervalo // 24} dias"
        else:
            freq = f"a cada {intervalo}h"
        if cortou_limite:
            extra = "\n(criei só até o seu limite de compromissos em aberto)"
        elif len(ocorrencias) >= _MAX_OCORRENCIAS:
            extra = f"\n(atingiu o limite de {_MAX_OCORRENCIAS} lembretes por série)"
        else:
            extra = ""
        ctx.reply(
            f"✅ Criei {len(ocorrencias)} lembretes de \"{dados['descricao']}\" — {freq}.\n"
            f"🕒 De {_fmt_datahora(ocorrencias[0])} até {_fmt_datahora(ocorrencias[-1])}.\n"
            f"Te aviso na hora de cada um. 🔔{extra}\n"
            "Para cancelar, veja em /lembretes.")
        return
    if is_reminder_add(text):
        ctx.typing()
        dados = extract_reminder(text, usuario_id)
        if not dados:
            ctx.reply(
                "Não consegui entender o compromisso. 😕\n"
                "Tente algo como: \"me avise amanhã às 9h da reunião com a Adriana\".")
            return
        if not _slots_compromissos(ctx, usuario_id, tenant):
            return
        reminders.add(usuario_id, dados["descricao"], dados["quando"], dados.get("avisar_em"))
        if dados.get("avisar_em"):
            aviso_txt = f"Te aviso em {_fmt_datahora(dados['avisar_em'])}."
        else:
            antecedencia = tenant.get("AntecedenciaMin", 15)
            aviso_txt = f"Te aviso cerca de {antecedencia} min antes."
        ctx.reply(
            f"✅ Lembrete agendado: {dados['descricao']} — {_fmt_datahora(dados['quando'])}.\n"
            f"{aviso_txt} 🔔")
        return

    # --- Conversa geral (com contexto de clima/web quando fizer sentido) ---
    ctx.typing()
    try:
        extra = weather_context(tenant, text) or web_context(text)
    except Exception:
        log.exception("Erro ao montar contexto (clima/web)")
        extra = None
    try:
        reply = llm.ask_hermes(usuario_id, text, extra_context=extra)
    except Exception as e:
        log.exception("Erro ao consultar Hermes")
        ctx.reply(f"⚠️ Erro ao gerar resposta: {e}")
        return
    ctx.reply(reply)
