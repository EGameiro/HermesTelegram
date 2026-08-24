"""Voz agnóstica de canal: transcrição (Whisper) e síntese (TTS) da OpenAI.

O download do áudio recebido e o envio do áudio gerado são responsabilidade de cada
adaptador de canal (no WhatsApp, via UAZAPI). Aqui ficam só as etapas neutras:
bytes de áudio -> texto (transcrever) e texto -> bytes (tts)."""
import shutil
import logging
import subprocess

import requests

import config

log = logging.getLogger("hermes.voice")


def transcrever(audio_bytes, filename="audio.ogg", mime="audio/ogg"):
    """Transcreve bytes de áudio via Whisper da OpenAI. Retorna texto ou None."""
    if not config.OPENAI_API_KEY or not audio_bytes:
        return None
    try:
        r = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            files={"file": (filename, audio_bytes, mime)},
            data={"model": config.OPENAI_STT_MODEL, "language": "pt"},
            timeout=120,
        )
        r.raise_for_status()
        return (r.json().get("text") or "").strip()
    except Exception:
        log.exception("Falha ao transcrever áudio")
        return None


def _normalizar_volume(audio_bytes):
    """Normaliza o volume (loudnorm ~ -16 LUFS) via ffmpeg — o TTS da OpenAI sai baixo
    demais (quase inaudível). Sem ffmpeg ou em falha, devolve os bytes originais."""
    if not audio_bytes or not shutil.which("ffmpeg"):
        return audio_bytes
    try:
        p = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
             "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
             "-c:a", "libopus", "-b:a", "48000", "-ar", "48000", "-ac", "1",
             "-f", "ogg", "pipe:1"],
            input=audio_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        if p.returncode == 0 and p.stdout:
            return p.stdout
        log.warning("Normalização de áudio falhou (rc=%s); enviando original.", p.returncode)
    except Exception:
        log.exception("Erro ao normalizar áudio; enviando original.")
    return audio_bytes


def tts(texto):
    """Texto -> áudio Opus (bytes) via OpenAI TTS, com volume normalizado.
    Retorna bytes ou None em falha."""
    if not config.OPENAI_API_KEY:
        return None
    try:
        payload = {
            "model": config.OPENAI_TTS_MODEL,
            "voice": config.OPENAI_TTS_VOICE,
            "input": texto,
            "response_format": "opus",
        }
        # 'instructions' só existe nos modelos gpt-4o-*-tts (fixa o idioma pt-BR).
        if config.OPENAI_TTS_INSTRUCTIONS and config.OPENAI_TTS_MODEL.startswith("gpt-4o"):
            payload["instructions"] = config.OPENAI_TTS_INSTRUCTIONS
        r = requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        return _normalizar_volume(r.content)
    except Exception:
        log.exception("Falha ao gerar áudio (TTS)")
        return None
