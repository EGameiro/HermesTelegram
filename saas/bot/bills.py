"""Contas a pagar — multi-tenant no MySQL (H01ContasPagar), escopadas por UsuarioId.

Mesma API do protótipo, trocando `chat_id` por `usuario_id` (o tenant já resolvido).
Datas de vencimento são devolvidas como string ISO 'YYYY-MM-DD' para o bot formatar
como antes (o MySQL guarda DATE; PyMySQL devolve datetime.date -> convertemos aqui).
"""
import logging

import db

log = logging.getLogger("hermes-bot.bills")


def _map(row):
    """Normaliza uma linha de H01ContasPagar para as chaves que o bot espera."""
    if row is None:
        return None
    venc = row.get("vencimento")
    return {
        "id": row["id"],
        "usuario_id": row.get("usuario_id"),
        "descricao": row["descricao"],
        "valor": float(row["valor"]) if row.get("valor") is not None else None,
        "vencimento": venc.isoformat() if hasattr(venc, "isoformat") else venc,
    }


def add(usuario_id, descricao, valor, vencimento_iso):
    lastrowid, _ = db.execute(
        "INSERT INTO H01ContasPagar (UsuarioId, Descricao, Valor, Vencimento) "
        "VALUES (%s, %s, %s, %s)",
        (usuario_id, descricao, valor, vencimento_iso),
    )
    return lastrowid


def listar(usuario_id, incluir_pagas=False):
    sql = (
        "SELECT Id AS id, Descricao AS descricao, Valor AS valor, Vencimento AS vencimento "
        "FROM H01ContasPagar WHERE UsuarioId = %s"
    )
    if not incluir_pagas:
        sql += " AND Pago = 0"
    sql += " ORDER BY Vencimento"
    return [_map(r) for r in db.query_all(sql, (usuario_id,))]


def listar_periodo(usuario_id, ini_iso, fim_iso):
    """Contas pendentes com vencimento entre ini e fim (inclusive)."""
    rows = db.query_all(
        "SELECT Id AS id, Descricao AS descricao, Valor AS valor, Vencimento AS vencimento "
        "FROM H01ContasPagar "
        "WHERE UsuarioId = %s AND Pago = 0 AND Vencimento BETWEEN %s AND %s "
        "ORDER BY Vencimento",
        (usuario_id, ini_iso, fim_iso),
    )
    return [_map(r) for r in rows]


def marcar_pago(usuario_id, conta_id):
    _, rc = db.execute(
        "UPDATE H01ContasPagar SET Pago = 1 WHERE Id = %s AND UsuarioId = %s",
        (conta_id, usuario_id),
    )
    return rc > 0


def marcar_pago_por_descricao(usuario_id, termo):
    """Marca paga a 1ª conta pendente cuja descrição contém o termo. Retorna a conta ou None."""
    row = db.query_one(
        "SELECT Id AS id, Descricao AS descricao, Valor AS valor, Vencimento AS vencimento "
        "FROM H01ContasPagar "
        "WHERE UsuarioId = %s AND Pago = 0 AND LOWER(Descricao) LIKE %s "
        "ORDER BY Vencimento LIMIT 1",
        (usuario_id, f"%{termo.lower()}%"),
    )
    if not row:
        return None
    db.execute("UPDATE H01ContasPagar SET Pago = 1 WHERE Id = %s", (row["id"],))
    return _map(row)


def remover(usuario_id, conta_id):
    _, rc = db.execute(
        "DELETE FROM H01ContasPagar WHERE Id = %s AND UsuarioId = %s",
        (conta_id, usuario_id),
    )
    return rc > 0


def contar(usuario_id):
    """Quantidade total de contas (pagas ou não)."""
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM H01ContasPagar WHERE UsuarioId = %s",
        (usuario_id,),
    )
    return int(row["n"]) if row else 0


def vencendo(hoje_iso, hora_atual):
    """Contas de TODOS os tenants conectados, não pagas, vencidas (<= hoje), sem lembrete
    enviado, cujo horário de lembrete do tenant (HoraLembrete) já chegou.

    Devolve (canal, identificador) do destino e VozAtiva (formato do aviso). Um tenant
    conectado em mais de um canal gera uma linha por canal (avisado em cada um)."""
    rows = db.query_all(
        """
        SELECT
            c.Id            AS id,
            c.UsuarioId     AS usuario_id,
            c.Descricao     AS descricao,
            c.Valor         AS valor,
            c.Vencimento    AS vencimento,
            v.Canal              AS canal,
            v.IdentificadorCanal AS identificador,
            COALESCE(cfg.VozAtiva, 1) AS voz_ativa
        FROM H01ContasPagar c
        JOIN H01Vinculos v ON v.UsuarioId = c.UsuarioId
        LEFT JOIN H01Configuracoes cfg ON cfg.UsuarioId = c.UsuarioId
        WHERE c.Pago = 0
          AND c.LembreteEnviado = 0
          AND c.Vencimento <= %s
          AND v.StatusConexao = 'conectado'
          AND v.IdentificadorCanal IS NOT NULL
          AND %s >= COALESCE(cfg.HoraLembrete, 8)
        """,
        (hoje_iso, hora_atual),
    )
    out = []
    for r in rows:
        d = _map(r)
        d["canal"] = r["canal"]
        d["identificador"] = r["identificador"]
        d["voz_ativa"] = int(r["voz_ativa"])
        out.append(d)
    return out


def marcar_lembrete_enviado(conta_id):
    db.execute("UPDATE H01ContasPagar SET LembreteEnviado = 1 WHERE Id = %s", (conta_id,))
