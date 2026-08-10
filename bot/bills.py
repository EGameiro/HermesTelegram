"""Contas a pagar — armazenamento persistente em SQLite (num volume do Docker)."""
import os
import sqlite3
import logging
from datetime import datetime

log = logging.getLogger("hermes-bot.bills")

DB_PATH = os.environ.get("BILLS_DB", "/data/bills.db")


def _conn():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with _conn() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS contas(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                descricao TEXT NOT NULL,
                valor REAL,
                vencimento TEXT NOT NULL,          -- ISO YYYY-MM-DD
                pago INTEGER NOT NULL DEFAULT 0,
                lembrete_enviado INTEGER NOT NULL DEFAULT 0,
                criado_em TEXT NOT NULL
            )"""
        )
    log.info("Banco de contas pronto em %s", DB_PATH)


def add(chat_id, descricao, valor, vencimento_iso):
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO contas(chat_id,descricao,valor,vencimento,criado_em) VALUES(?,?,?,?,?)",
            (chat_id, descricao, valor, vencimento_iso, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def listar(chat_id, incluir_pagas=False):
    q = "SELECT * FROM contas WHERE chat_id=?"
    if not incluir_pagas:
        q += " AND pago=0"
    q += " ORDER BY vencimento"
    with _conn() as con:
        return [dict(r) for r in con.execute(q, (chat_id,)).fetchall()]


def listar_periodo(chat_id, ini_iso, fim_iso):
    """Contas pendentes com vencimento entre ini e fim (inclusive), ordenadas."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM contas WHERE chat_id=? AND pago=0 AND vencimento BETWEEN ? AND ? "
            "ORDER BY vencimento",
            (chat_id, ini_iso, fim_iso),
        ).fetchall()
        return [dict(r) for r in rows]


def marcar_pago(chat_id, conta_id):
    with _conn() as con:
        cur = con.execute("UPDATE contas SET pago=1 WHERE id=? AND chat_id=?", (conta_id, chat_id))
        return cur.rowcount > 0


def marcar_pago_por_descricao(chat_id, termo):
    """Marca paga a 1ª conta pendente cuja descrição contém o termo. Retorna a conta ou None."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM contas WHERE chat_id=? AND pago=0 AND lower(descricao) LIKE ? "
            "ORDER BY vencimento LIMIT 1",
            (chat_id, f"%{termo.lower()}%"),
        ).fetchone()
        if not row:
            return None
        con.execute("UPDATE contas SET pago=1 WHERE id=?", (row["id"],))
        return dict(row)


def remover(chat_id, conta_id):
    with _conn() as con:
        cur = con.execute("DELETE FROM contas WHERE id=? AND chat_id=?", (conta_id, chat_id))
        return cur.rowcount > 0


def vencendo(hoje_iso):
    """Contas não pagas, com vencimento <= hoje e sem lembrete enviado (todas as chats)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM contas WHERE pago=0 AND lembrete_enviado=0 AND vencimento<=?",
            (hoje_iso,),
        ).fetchall()
        return [dict(r) for r in rows]


def marcar_lembrete_enviado(conta_id):
    with _conn() as con:
        con.execute("UPDATE contas SET lembrete_enviado=1 WHERE id=?", (conta_id,))
