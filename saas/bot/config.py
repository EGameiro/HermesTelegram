"""Configuração compartilhada do núcleo do Hermes (env + helpers de tempo).

Centraliza tudo que era lido do ambiente no bot.py monolítico, para que núcleo e
adaptadores de canal leiam de um lugar só. NUNCA usar date.today()/datetime.now()
naive no código — sempre agora_local()/hoje_local() (o container roda em UTC).
"""
import os
import socket
from datetime import datetime
from zoneinfo import ZoneInfo

# --- Força IPv4 (process-wide) ----------------------------------------------
# Em máquinas com IPv6 quebrado, cada conexão HTTPS NOVA (Groq/OpenAI/UAZAPI) trava
# ~21s no timeout do SYN antes de cair pro IPv4. Filtrando o getaddrinfo para IPv4 o
# handshake volta ao normal. Seguro: se não houver IPv4, mantém a lista original.
# Desligue com FORCE_IPV4=0. (Aplica-se ao processo todo; importe config cedo.)
if os.environ.get("FORCE_IPV4", "1").lower() not in ("0", "false", "no"):
    _orig_getaddrinfo = socket.getaddrinfo

    def _getaddrinfo_ipv4(*args, **kwargs):
        res = _orig_getaddrinfo(*args, **kwargs)
        v4 = [r for r in res if r[0] == socket.AF_INET]
        return v4 or res

    socket.getaddrinfo = _getaddrinfo_ipv4

# --- Cérebro (LLM) ----------------------------------------------------------
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "hermes3:3b")
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()  # "ollama" | "groq"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")  # llama-3.3-70b foi descomissionado
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    "Você é o Hermes, um assistente útil e direto. Responda em português do Brasil.",
)
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "12"))
REQUEST_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "300"))

# --- Fuso / features --------------------------------------------------------
TZ = os.environ.get("TZ", "America/Sao_Paulo")
WEATHER_ENABLED = os.environ.get("WEATHER_ENABLED", "true").lower() != "false"
WEBSEARCH_ENABLED = os.environ.get("WEBSEARCH_ENABLED", "true").lower() != "false"
BILLS_ENABLED = os.environ.get("BILLS_ENABLED", "true").lower() != "false"
REMINDERS_ENABLED = os.environ.get("REMINDERS_ENABLED", "true").lower() != "false"

# --- Voz (OpenAI: Whisper STT + TTS) ----------------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")  # vazio = voz off
OPENAI_STT_MODEL = os.environ.get("OPENAI_STT_MODEL", "whisper-1")
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "nova")
OPENAI_TTS_INSTRUCTIONS = os.environ.get(
    "OPENAI_TTS_INSTRUCTIONS",
    "Fale sempre em português do Brasil, com pronúncia natural. "
    "Pronuncie TODOS os números, valores em reais, horários e datas em português — nunca em inglês.",
)
REMINDER_VOICE = os.environ.get("REMINDER_VOICE", "true").lower() != "false"  # lembrete em áudio

TIMING = os.environ.get("HERMES_TIMING", "").lower() in ("1", "true", "yes")


def agora_local():
    """Data/hora atual no fuso configurado (aware)."""
    return datetime.now(ZoneInfo(TZ))


def hoje_local():
    return agora_local().date()
