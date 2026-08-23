"""Resolução de tenant (Modelo A: identidade pelo TelegramUserId) + vínculo por token
+ configurações do assistente por usuário.

Cada USUÁRIO é um tenant. Um TelegramUserId -> uma conta (UNIQUE no schema).
Toda operação de domínio (contas/compromissos) recebe o UsuarioId resolvido aqui —
nunca o chat_id cru vindo do Telegram.
"""
import logging
from datetime import datetime

import db

log = logging.getLogger("hermes-bot.tenants")

# Cache em memória: telegram_user_id -> dict do tenant (ou None se não resolvido).
# Invalida no /start (vínculo) para não servir estado velho.
_cache: dict[int, dict | None] = {}

# Status de usuário que PODEM usar o bot.
_STATUS_ATIVOS = {"trial", "ativo"}

# Defaults de configuração (espelham os DEFAULT do schema H01Configuracoes).
_CONFIG_DEFAULT = {
    "Cidade": "Jacareí",
    "VozAtiva": 1,
    "HoraLembrete": 8,
    "AntecedenciaMin": 15,
    "LimiteCompromissos": 100,   # máx. de compromissos em aberto
    "LimiteContas": 300,         # máx. de contas (pagas ou não)
    "Pin": None,
    "Fuso": "America/Sao_Paulo",
}


_plano_free_cache: dict | None = None


def _plano_free():
    """Limites do plano 'free' (cacheados) — fallback p/ contas sem assinatura ativa."""
    global _plano_free_cache
    if _plano_free_cache is None:
        _plano_free_cache = db.query_one(
            "SELECT LimiteVozSegMes, LimiteMsgsDia FROM H01Planos WHERE Codigo = 'free' LIMIT 1"
        ) or {}
    return _plano_free_cache or None


def resolve(telegram_user_id: int) -> dict | None:
    """Resolve o tenant a partir do TelegramUserId. Retorna dict com
    {usuario_id, status, plano_codigo, limite_voz_seg, config...} ou None se o
    Telegram não estiver vinculado a nenhuma conta ativa."""
    if telegram_user_id in _cache:
        return _cache[telegram_user_id]

    row = db.query_one(
        """
        SELECT
            v.UsuarioId          AS usuario_id,
            v.StatusConexao      AS status_conexao,
            u.Status             AS status_usuario,
            u.NomeCompleto       AS nome,
            p.Codigo             AS plano_codigo,
            p.LimiteVozSegMes    AS limite_voz_seg,
            p.LimiteMsgsDia      AS limite_msgs_dia
        FROM H01TelegramVinculos v
        JOIN H01Usuarios   u ON u.Id = v.UsuarioId
        LEFT JOIN H01Assinaturas a ON a.UsuarioId = u.Id
        LEFT JOIN H01Planos       p ON p.Id = a.PlanoId
        WHERE v.TelegramUserId = %s AND v.StatusConexao = 'conectado'
        ORDER BY a.CriadoEm DESC
        LIMIT 1
        """,
        (telegram_user_id,),
    )

    if not row or row["status_usuario"] not in _STATUS_ATIVOS:
        _cache[telegram_user_id] = None
        return None

    # Sem assinatura ativa -> aplica os limites do plano 'free' (evita conceder voz
    # ilimitada por engano; None só significa "ilimitado" quando o plano define assim).
    if row["plano_codigo"] is None:
        free = _plano_free()
        plano_codigo = "free"
        limite_voz = free["LimiteVozSegMes"] if free else 0
        limite_msgs = free["LimiteMsgsDia"] if free else None
    else:
        plano_codigo = row["plano_codigo"]
        limite_voz = row["limite_voz_seg"]
        limite_msgs = row["limite_msgs_dia"]

    tenant = {
        "usuario_id": int(row["usuario_id"]),
        "nome": row["nome"],
        "plano_codigo": plano_codigo,
        "limite_voz_seg": limite_voz,   # None = ilimitado (só planos pagos)
        "limite_msgs_dia": limite_msgs,
    }
    tenant.update(get_config(tenant["usuario_id"]))
    _cache[telegram_user_id] = tenant
    return tenant


def invalidate(telegram_user_id: int):
    _cache.pop(telegram_user_id, None)


def vincular(token: str, telegram_user_id: int, username: str | None):
    """Consome um TokenVinculo de uso único e amarra o Telegram à conta.

    Retorna (ok: bool, mensagem: str)."""
    token = (token or "").strip()
    if not token:
        return False, "Código de vínculo vazio."

    vinc = db.query_one(
        """
        SELECT v.Id, v.UsuarioId, v.TokenExpiraEm, u.NomeCompleto, u.Status
        FROM H01TelegramVinculos v
        JOIN H01Usuarios u ON u.Id = v.UsuarioId
        WHERE v.TokenVinculo = %s
        LIMIT 1
        """,
        (token,),
    )
    if not vinc:
        return False, "Código inválido. Gere um novo código no painel e tente de novo."

    if vinc["TokenExpiraEm"] and vinc["TokenExpiraEm"] < datetime.now():
        return False, "Esse código expirou. Gere um novo no painel."

    if vinc["Status"] not in _STATUS_ATIVOS:
        return False, "Sua conta não está ativa. Fale com o suporte."

    # Esse Telegram já está vinculado a outra conta?
    outro = db.query_one(
        "SELECT UsuarioId FROM H01TelegramVinculos "
        "WHERE TelegramUserId = %s AND UsuarioId <> %s LIMIT 1",
        (telegram_user_id, vinc["UsuarioId"]),
    )
    if outro:
        return False, (
            "Este Telegram já está conectado a outra conta. "
            "Desconecte-a primeiro no painel."
        )

    db.execute(
        """
        UPDATE H01TelegramVinculos
           SET TelegramUserId   = %s,
               TelegramUsername = %s,
               StatusConexao    = 'conectado',
               TokenVinculo     = NULL,
               TokenExpiraEm    = NULL,
               DataVinculo      = %s
         WHERE Id = %s
        """,
        (telegram_user_id, username, datetime.now(), vinc["Id"]),
    )
    ensure_config(vinc["UsuarioId"])
    invalidate(telegram_user_id)
    log.info("Telegram %s vinculado ao usuário %s.", telegram_user_id, vinc["UsuarioId"])
    return True, f"✅ Conta conectada, {vinc['NomeCompleto'].split()[0]}! Pode começar a usar o Hermes. 🚀"


def ensure_config(usuario_id: int):
    """Garante uma linha em H01Configuracoes (idempotente)."""
    db.execute(
        "INSERT IGNORE INTO H01Configuracoes (UsuarioId) VALUES (%s)",
        (usuario_id,),
    )


def get_config(usuario_id: int) -> dict:
    """Configurações do assistente (com defaults se a linha não existir ainda)."""
    row = db.query_one(
        "SELECT Cidade, VozAtiva, HoraLembrete, AntecedenciaMin, "
        "LimiteCompromissos, LimiteContas, Pin, Fuso "
        "FROM H01Configuracoes WHERE UsuarioId = %s",
        (usuario_id,),
    )
    cfg = dict(_CONFIG_DEFAULT)
    if row:
        cfg.update({k: v for k, v in row.items() if v is not None})
    return cfg


def set_cidade(usuario_id: int, cidade: str):
    ensure_config(usuario_id)
    db.execute(
        "UPDATE H01Configuracoes SET Cidade = %s WHERE UsuarioId = %s",
        (cidade, usuario_id),
    )
