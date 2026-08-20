"""Compromissos com hora marcada — multi-tenant no MySQL (H01Compromissos), por UsuarioId.

Mesma API do protótipo, trocando `chat_id` por `usuario_id`. O campo Quando é DATETIME;
devolvemos como string ISO 'YYYY-MM-DDTHH:MM:SS' para o bot formatar como antes.
"""
import logging

import db

log = logging.getLogger("hermes-bot.reminders")


def _map(row):
    if row is None:
        return None
    q = row.get("quando")
    return {
        "id": row["id"],
        "usuario_id": row.get("usuario_id"),
        "descricao": row["descricao"],
        "quando": q.isoformat() if hasattr(q, "isoformat") else q,
    }


def add(usuario_id, descricao, quando_iso, avisar_em_iso=None):
    # MySQL DATETIME aceita 'YYYY-MM-DD HH:MM' — troca o 'T' do ISO por espaço.
    quando_sql = (quando_iso or "").replace("T", " ")
    # AvisarEm: horário explícito do lembrete (NULL = usar AntecedenciaMin do usuário).
    avisar_sql = avisar_em_iso.replace("T", " ") if avisar_em_iso else None
    lastrowid, _ = db.execute(
        "INSERT INTO H01Compromissos (UsuarioId, Descricao, Quando, AvisarEm) VALUES (%s, %s, %s, %s)",
        (usuario_id, descricao, quando_sql, avisar_sql),
    )
    return lastrowid


def listar(usuario_id):
    rows = db.query_all(
        "SELECT Id AS id, Descricao AS descricao, Quando AS quando "
        "FROM H01Compromissos WHERE UsuarioId = %s AND Avisado = 0 ORDER BY Quando",
        (usuario_id,),
    )
    return [_map(r) for r in rows]


def listar_periodo(usuario_id, ini_date_iso, fim_date_iso):
    """Compromissos não avisados cuja DATA está entre ini e fim (inclusive)."""
    rows = db.query_all(
        "SELECT Id AS id, Descricao AS descricao, Quando AS quando "
        "FROM H01Compromissos "
        "WHERE UsuarioId = %s AND Avisado = 0 AND DATE(Quando) BETWEEN %s AND %s "
        "ORDER BY Quando",
        (usuario_id, ini_date_iso, fim_date_iso),
    )
    return [_map(r) for r in rows]


def remover(usuario_id, lid):
    _, rc = db.execute(
        "DELETE FROM H01Compromissos WHERE Id = %s AND UsuarioId = %s",
        (lid, usuario_id),
    )
    return rc > 0


def due(agora_dt):
    """Compromissos de TODOS os tenants conectados, não avisados, cujo momento de aviso já chegou.

    O momento de aviso é AvisarEm (horário explícito escolhido pelo usuário) quando definido;
    caso contrário é Quando menos a AntecedenciaMin do tenant (padrão 15 min).

    Devolve também o TelegramUserId (destino) e VozAtiva (formato do aviso)."""
    rows = db.query_all(
        """
        SELECT
            l.Id            AS id,
            l.UsuarioId     AS usuario_id,
            l.Descricao     AS descricao,
            l.Quando        AS quando,
            v.TelegramUserId AS telegram_user_id,
            COALESCE(cfg.VozAtiva, 1) AS voz_ativa
        FROM H01Compromissos l
        JOIN H01TelegramVinculos v ON v.UsuarioId = l.UsuarioId
        LEFT JOIN H01Configuracoes cfg ON cfg.UsuarioId = l.UsuarioId
        WHERE l.Avisado = 0
          AND v.StatusConexao = 'conectado'
          AND v.TelegramUserId IS NOT NULL
          AND COALESCE(l.AvisarEm, l.Quando - INTERVAL COALESCE(cfg.AntecedenciaMin, 15) MINUTE) <= %s
        ORDER BY l.Quando
        """,
        (agora_dt.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    out = []
    for r in rows:
        d = _map(r)
        d["telegram_user_id"] = r["telegram_user_id"]
        d["voz_ativa"] = int(r["voz_ativa"])
        out.append(d)
    return out


def marcar_avisado(lid):
    db.execute("UPDATE H01Compromissos SET Avisado = 1 WHERE Id = %s", (lid,))
