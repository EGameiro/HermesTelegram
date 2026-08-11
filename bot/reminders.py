"""Lembretes/compromissos com hora marcada — SQLite (mesmo banco das contas, outra tabela)."""
import os
import sqlite3
import logging
from datetime import datetime

log = logging.getLogger("hermes-bot.reminders")

DB_PATH = os.environ.get("BILLS_DB", "/data/bills.db")


def _conn():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with _conn() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS lembretes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                descricao TEXT NOT NULL,
                quando TEXT NOT NULL,              -- ISO 'YYYY-MM-DDTHH:MM'
                avisado INTEGER NOT NULL DEFAULT 0,
                criado_em TEXT NOT NULL
            )"""
        )
    log.info("Tabela de lembretes pronta em %s", DB_PATH)


def add(chat_id, descricao, quando_iso):
    with _conn() as con:
        cur = con.execute(
            "INSERT INTO lembretes(chat_id,descricao,quando,criado_em) VALUES(?,?,?,?)",
            (chat_id, descricao, quando_iso, datetime.now().isoformat(timespec="seconds")),
        )
        return cur.lastrowid


def listar(chat_id):
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM lembretes WHERE chat_id=? AND avisado=0 ORDER BY quando", (chat_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def listar_periodo(chat_id, ini_date_iso, fim_date_iso):
    """Compromissos não avisados cuja DATA está entre ini e fim (inclusive)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM lembretes WHERE chat_id=? AND avisado=0 AND quando BETWEEN ? AND ? "
            "ORDER BY quando",
            (chat_id, f"{ini_date_iso}T00:00", f"{fim_date_iso}T23:59"),
        ).fetchall()
        return [dict(r) for r in rows]


def remover(chat_id, lid):
    with _conn() as con:
        cur = con.execute("DELETE FROM lembretes WHERE id=? AND chat_id=?", (lid, chat_id))
        return cur.rowcount > 0


def due(limite_iso):
    """Lembretes não avisados cujo horário já é <= limite (agora + antecedência)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM lembretes WHERE avisado=0 AND quando<=? ORDER BY quando", (limite_iso,)
        ).fetchall()
        return [dict(r) for r in rows]


def marcar_avisado(lid):
    with _conn() as con:
        con.execute("UPDATE lembretes SET avisado=1 WHERE id=?", (lid,))
