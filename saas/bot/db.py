"""Camada de acesso ao MySQL 8 (multi-tenant). Contrato: schema em saas/database/schema.sql.

Conexões curtas por operação (como o SQLite fazia): simples e seguro em thread
(o long polling e o agendador rodam em threads distintas). Sem pool por ora — o
volume é baixo. Se precisar, trocar por DBUtils.PooledDB sem mexer nos callers.
"""
import os
import logging

import pymysql
from pymysql.cursors import DictCursor

log = logging.getLogger("hermes-bot.db")

_CFG = {
    "host": os.environ.get("MYSQL_HOST", "localhost"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "database": os.environ.get("MYSQL_DB", "hermes_saas"),
    "charset": "utf8mb4",
    "autocommit": True,          # cada execute() confirma sozinho
    "cursorclass": DictCursor,   # linhas como dict (chaves = nomes/aliases das colunas)
    "connect_timeout": 10,
    "read_timeout": 30,
    "write_timeout": 30,
}


def _connect():
    return pymysql.connect(**_CFG)


def query_all(sql, params=None):
    """Lista de dicts (pode ser vazia)."""
    con = _connect()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        con.close()


def query_one(sql, params=None):
    """Primeiro dict ou None."""
    con = _connect()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
    finally:
        con.close()


def execute(sql, params=None):
    """Executa INSERT/UPDATE/DELETE. Retorna (lastrowid, rowcount)."""
    con = _connect()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.lastrowid, cur.rowcount
    finally:
        con.close()


def ping():
    """Testa a conexão no startup. Levanta exceção se o banco não responder."""
    con = _connect()
    try:
        con.ping(reconnect=True)
        log.info(
            "Conectado ao MySQL %s:%s/%s.",
            _CFG["host"], _CFG["port"], _CFG["database"],
        )
    finally:
        con.close()
