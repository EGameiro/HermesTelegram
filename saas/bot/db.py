"""Camada de acesso ao MySQL 8 (multi-tenant). Contrato: schema em saas/database/schema.sql.

Usa um POOL de conexões (DBUtils.PooledDB) para reaproveitar conexões em vez de reconectar
a cada consulta — importante quando o banco é remoto (o handshake/auth pela internet é caro).
Thread-safe: o long polling e o agendador compartilham o mesmo pool.
"""
import os
import time
import logging

import pymysql
from pymysql.cursors import DictCursor
from dbutils.pooled_db import PooledDB

log = logging.getLogger("hermes-bot.db")

_TIMING = os.environ.get("HERMES_TIMING", "").lower() in ("1", "true", "yes")


def _log_ms(label, t0):
    if _TIMING:
        log.info("[t] DB %s: %.0f ms", label, (time.perf_counter() - t0) * 1000)

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

# Pool compartilhado. ping=1 revalida a conexão ao tirá-la do pool (o servidor pode
# derrubar conexões ociosas); maxconnections limita o total simultâneo.
_pool = PooledDB(
    creator=pymysql,
    maxconnections=int(os.environ.get("MYSQL_POOL_MAX", "8")),
    mincached=1,
    maxcached=4,
    blocking=True,
    ping=1,
    **_CFG,
)


def _connect():
    """Conexão do pool. O .close() devolve a conexão ao pool (não fecha de verdade)."""
    return _pool.connection()


def query_all(sql, params=None):
    """Lista de dicts (pode ser vazia)."""
    t0 = time.perf_counter()
    con = _connect()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        con.close()
        _log_ms("query_all", t0)


def query_one(sql, params=None):
    """Primeiro dict ou None."""
    t0 = time.perf_counter()
    con = _connect()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
    finally:
        con.close()
        _log_ms("query_one", t0)


def execute(sql, params=None):
    """Executa INSERT/UPDATE/DELETE. Retorna (lastrowid, rowcount)."""
    t0 = time.perf_counter()
    con = _connect()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.lastrowid, cur.rowcount
    finally:
        con.close()
        _log_ms("execute", t0)


def ping():
    """Testa o pool no startup. Levanta exceção se o banco não responder."""
    con = _connect()
    try:
        with con.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        log.info(
            "Pool de conexões MySQL pronto (%s:%s/%s).",
            _CFG["host"], _CFG["port"], _CFG["database"],
        )
    finally:
        con.close()
