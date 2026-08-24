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


def set_google_event(lid, google_event_id):
    """Guarda o id do evento espelhado na Google Agenda para este compromisso."""
    db.execute(
        "UPDATE H01Compromissos SET GoogleEventId = %s WHERE Id = %s",
        (google_event_id, lid),
    )


def google_event_id(usuario_id, lid):
    """Id do evento no Google deste compromisso (ou None)."""
    row = db.query_one(
        "SELECT GoogleEventId FROM H01Compromissos WHERE Id = %s AND UsuarioId = %s",
        (lid, usuario_id),
    )
    return (row or {}).get("GoogleEventId")


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

    Devolve (canal, identificador) do destino e VozAtiva (formato do aviso). Um tenant
    conectado em mais de um canal gera uma linha por canal (avisado em cada um)."""
    rows = db.query_all(
        """
        SELECT
            l.Id            AS id,
            l.UsuarioId     AS usuario_id,
            l.Descricao     AS descricao,
            l.Quando        AS quando,
            v.Canal              AS canal,
            v.IdentificadorCanal AS identificador,
            COALESCE(cfg.VozAtiva, 1) AS voz_ativa
        FROM H01Compromissos l
        JOIN H01Vinculos v ON v.UsuarioId = l.UsuarioId
        LEFT JOIN H01Configuracoes cfg ON cfg.UsuarioId = l.UsuarioId
        WHERE l.Avisado = 0
          AND v.StatusConexao = 'conectado'
          AND v.IdentificadorCanal IS NOT NULL
          AND COALESCE(l.AvisarEm, l.Quando - INTERVAL COALESCE(cfg.AntecedenciaMin, 15) MINUTE) <= %s
        ORDER BY l.Quando
        """,
        (agora_dt.strftime("%Y-%m-%d %H:%M:%S"),),
    )
    out = []
    for r in rows:
        d = _map(r)
        d["canal"] = r["canal"]
        d["identificador"] = r["identificador"]
        d["voz_ativa"] = int(r["voz_ativa"])
        out.append(d)
    return out


def marcar_avisado(lid):
    db.execute("UPDATE H01Compromissos SET Avisado = 1 WHERE Id = %s", (lid,))


def contar_abertos(usuario_id):
    """Quantidade de compromissos EM ABERTO (ainda não avisados)."""
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM H01Compromissos WHERE UsuarioId = %s AND Avisado = 0",
        (usuario_id,),
    )
    return int(row["n"]) if row else 0
