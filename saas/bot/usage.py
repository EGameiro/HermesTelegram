"""Medição de uso por tenant/mês (H01UsoMensal) — base de custo (COGS) e limites (fair-use).

Mede: tokens de LLM, segundos de voz recebida (Whisper), caracteres de TTS e nº de
mensagens. A contagem reinicia no 1º dia de cada mês (chave UsuarioId+Ano+Mes).
O limite de voz do plano grátis é aplicado a partir de SegundosVoz do mês corrente.
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
import os

import db

log = logging.getLogger("hermes-bot.usage")

TZ = os.environ.get("TZ", "America/Sao_Paulo")


def _ano_mes():
    agora = datetime.now(ZoneInfo(TZ))
    return agora.year, agora.month


def registrar(usuario_id, *, tokens=0, segundos_voz=0, caracteres_tts=0, mensagens=0):
    """Soma consumo no mês corrente (upsert). Nunca deixa a medição derrubar o fluxo."""
    if not usuario_id:
        return
    if not (tokens or segundos_voz or caracteres_tts or mensagens):
        return
    ano, mes = _ano_mes()
    try:
        db.execute(
            """
            INSERT INTO H01UsoMensal
                (UsuarioId, Ano, Mes, TokensLlm, SegundosVoz, CaracteresTts, QtdMensagens)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                TokensLlm     = TokensLlm     + VALUES(TokensLlm),
                SegundosVoz   = SegundosVoz   + VALUES(SegundosVoz),
                CaracteresTts = CaracteresTts + VALUES(CaracteresTts),
                QtdMensagens  = QtdMensagens  + VALUES(QtdMensagens)
            """,
            (usuario_id, ano, mes, tokens, segundos_voz, caracteres_tts, mensagens),
        )
    except Exception:
        log.exception("Falha ao registrar uso do usuário %s", usuario_id)


def voz_usada_mes(usuario_id) -> int:
    """Segundos de voz já consumidos no mês corrente."""
    ano, mes = _ano_mes()
    row = db.query_one(
        "SELECT SegundosVoz AS s FROM H01UsoMensal "
        "WHERE UsuarioId = %s AND Ano = %s AND Mes = %s",
        (usuario_id, ano, mes),
    )
    return int(row["s"]) if row and row["s"] is not None else 0


def voz_permitida(tenant, segundos_previstos=0) -> tuple[bool, int]:
    """Diz se o tenant ainda pode usar voz este mês.

    Retorna (permitido, restante_seg). Limite None = ilimitado (planos pagos)."""
    limite = tenant.get("limite_voz_seg")
    if limite is None:
        return True, -1  # ilimitado
    usado = voz_usada_mes(tenant["usuario_id"])
    restante = int(limite) - usado
    return (usado + max(segundos_previstos, 0) <= int(limite)), max(restante, 0)


def _fmt_min(segundos) -> str:
    m = segundos // 60
    s = segundos % 60
    if m and s:
        return f"{m} min {s}s"
    if m:
        return f"{m} min"
    return f"{s}s"
