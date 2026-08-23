"""Cérebro do Hermes: chamada ao LLM (Ollama local ou Groq nuvem), prompt de sistema
com data/hora real e memória de conversa por tenant. Agnóstico de canal."""
import time
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

import config
import usage

log = logging.getLogger("hermes.llm")

# Memória de conversa em memória, escopada por UsuarioId (o tenant).
history: dict[int, list[dict]] = {}

_DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
         "sexta-feira", "sábado", "domingo"]


def llm_chat(messages, temperature=None, usuario_id=None):
    """Chama o provedor de LLM ativo e devolve o TEXTO. Se usuario_id for passado,
    mede os tokens consumidos em H01UsoMensal."""
    t0 = time.perf_counter()
    if config.LLM_PROVIDER == "groq":
        payload = {"model": config.GROQ_MODEL, "messages": messages, "stream": False}
        if temperature is not None:
            payload["temperature"] = temperature
        r = requests.post(
            config.GROQ_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            json=payload,
            timeout=config.REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        texto = data["choices"][0]["message"]["content"]
        tokens = int((data.get("usage") or {}).get("total_tokens", 0) or 0)
    else:
        payload = {"model": config.OLLAMA_MODEL, "messages": messages, "stream": False}
        if temperature is not None:
            payload["options"] = {"temperature": temperature}
        r = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        texto = data["message"]["content"]
        tokens = int(data.get("prompt_eval_count", 0) or 0) + int(data.get("eval_count", 0) or 0)

    if config.TIMING:
        log.info("[t] LLM %s: %.0f ms, %d tokens", config.LLM_PROVIDER, (time.perf_counter() - t0) * 1000, tokens)
    if usuario_id and tokens:
        usage.registrar(usuario_id, tokens=tokens)
    return texto


def system_prompt_agora():
    """O modelo não tem relógio próprio — injetamos a data/hora real a cada mensagem."""
    now = datetime.now(ZoneInfo(config.TZ))
    dia = _DIAS[now.weekday()]
    capacidades = ""
    if config.BILLS_ENABLED or config.REMINDERS_ENABLED:
        capacidades = (
            "\n\nVOCÊ É A FERRAMENTA. Aqui mesmo você gerencia diretamente as "
            "CONTAS A PAGAR e os COMPROMISSOS/LEMBRETES do usuário — você mesmo cadastra, lista "
            "e avisa no horário. NUNCA sugira nem cite apps/serviços externos (Google Calendar, "
            "agenda, Todoist, Alexa, Siri, alarme do celular, post-it, e-mail) para isso, e NUNCA "
            "diga que 'não consegue criar lembretes' — você consegue.\n"
            "- Criar compromisso/lembrete: se faltar a DATA ou a HORA, apenas PEÇA ('Pra qual dia "
            "e horário?'). Não recuse nem mande usar outro app.\n"
            "- Recorrente (repete em intervalos): aceite frases como 'tomar remédio de 8 em 8 horas "
            "a partir de hoje às 10h por 5 dias' ou 'ir ao médico todo dia às 10h por 10 dias'.\n"
            "- Ver a agenda: diga que basta pedir 'quais compromissos eu tenho' (ou por período: "
            "hoje, amanhã, essa semana).\n"
            "- Contas: cadastrar = dizer descrição, valor e vencimento; recorrente = 'conta de "
            "condomínio de 600 reais, vencimento todo dia 15, por 12 meses'; ver o total = 'quanto "
            "tenho pra pagar esse mês'; marcar paga = 'marca a conta número X como paga' ou "
            "'já paguei a conta X'; excluir = 'apaga a conta número X' ou 'cancela a conta número X'.\n"
            "IMPORTANTE: você NÃO executa essas ações dentro desta conversa — quem cadastra, marca "
            "paga, lista ou cancela é o SISTEMA, quando o usuário usa as frases certas. Então NUNCA "
            "afirme que já cadastrou, marcou como paga, cancelou ou salvou algo. Se um pedido de ação "
            "chegou até você, é porque NÃO foi reconhecido: então oriente o usuário a repetir com a "
            "frase certa (ex.: 'marca a conta número 12 como paga'), sem fingir que a ação foi feita."
        )
    return (
        f"{config.SYSTEM_PROMPT}\n\n"
        f"AGORA: hoje é {dia}, {now.strftime('%d/%m/%Y')}, e são {now.strftime('%H:%M')} "
        f"(horário de {config.TZ}). Ao falar de data, dia da semana ou hora, use EXATAMENTE "
        f"esses valores — não recalcule nem mude o dia da semana.\n"
        f"Responda normalmente usando o seu conhecimento — a maioria das perguntas "
        f"(explicações, conceitos, história, ajuda, ideias, etc.) você sabe responder e "
        f"deve responder à vontade. A ÚNICA exceção são dados que mudam em tempo real e "
        f"que não foram fornecidos a você nesta conversa (ex.: previsão do tempo, notícias "
        f"de hoje, cotações, placares ao vivo): apenas nesses casos, diga que não tem essa "
        f"informação atualizada, em vez de inventar. Nunca recuse uma pergunta comum de "
        f"conhecimento geral alegando falta de internet."
        f"{capacidades}"
    )


def ask_hermes(usuario_id, user_text, extra_context=None):
    """Conversa geral: monta prompt + histórico do tenant, chama o LLM, atualiza a memória."""
    msgs = [{"role": "system", "content": system_prompt_agora()}]
    if extra_context:
        msgs.append({"role": "system", "content": extra_context})
    msgs += history.get(usuario_id, [])
    msgs.append({"role": "user", "content": user_text})

    reply = llm_chat(msgs, usuario_id=usuario_id).strip()

    h = history.get(usuario_id, [])
    h.append({"role": "user", "content": user_text})
    h.append({"role": "assistant", "content": reply})
    history[usuario_id] = h[-config.MAX_HISTORY:]
    return reply


def reset(usuario_id):
    history.pop(usuario_id, None)


def ensure_model():
    """Espera o Ollama subir e baixa o modelo se ainda não estiver presente. Idempotente.
    Só usado quando LLM_PROVIDER=ollama."""
    log.info("Verificando modelo %s no Ollama em %s ...", config.OLLAMA_MODEL, config.OLLAMA_URL)
    for _ in range(60):
        try:
            requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
            break
        except Exception:
            log.info("Aguardando Ollama ficar disponível...")
            time.sleep(3)
    else:
        log.error("Ollama não respondeu a tempo — o bot vai tentar mesmo assim.")
        return

    wanted = config.OLLAMA_MODEL if ":" in config.OLLAMA_MODEL else f"{config.OLLAMA_MODEL}:latest"
    tags = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=10).json()
    names = [m.get("name", "") for m in tags.get("models", [])]
    if wanted in names:
        log.info("Modelo %s já presente. OK.", wanted)
        return

    log.info("Baixando modelo %s (pode demorar na primeira vez)...", config.OLLAMA_MODEL)
    with requests.post(f"{config.OLLAMA_URL}/api/pull", json={"name": config.OLLAMA_MODEL},
                       stream=True, timeout=None) as r:
        for line in r.iter_lines():
            if line:
                log.info("pull: %s", line.decode("utf-8", "ignore")[:200])
    log.info("Download concluído.")
