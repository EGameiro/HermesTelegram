"""Resolução de tenant por (canal, identificador) + vínculo por token + config por usuário.

Cada USUÁRIO é um tenant. A identidade vem SEMPRE do canal autenticado, nunca do input:
- telegram: identificador = TelegramUserId
- whatsapp: identificador = telefone (só dígitos)

Backend: tabela genérica H01Vinculos (Canal + IdentificadorCanal). Um usuário pode ter
um vínculo por canal. O token de onboarding é gerado pelo painel numa linha (UsuarioId,
Canal) e consumido aqui pelo /start (Telegram) ou pelo código digitado (WhatsApp).
"""
import logging
from datetime import datetime

import db

log = logging.getLogger("hermes.tenants")

# Cache em memória: (canal, identificador) -> dict do tenant (ou None). Invalida no vínculo.
_cache: dict[tuple[str, str], dict | None] = {}

_STATUS_ATIVOS = {"trial", "ativo"}

_CONFIG_DEFAULT = {
    "Cidade": "Jacareí",
    "VozAtiva": 1,
    "HoraLembrete": 8,
    "AntecedenciaMin": 15,
    "LimiteCompromissos": 100,
    "LimiteContas": 300,
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


def resolve(canal: str, identificador: str) -> dict | None:
    """Resolve o tenant a partir de (canal, identificador). Retorna dict com
    {usuario_id, status, plano_codigo, limite_voz_seg, config...} ou None se não vinculado
    a uma conta ativa."""
    chave = (canal, str(identificador))
    if chave in _cache:
        return _cache[chave]

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
        FROM H01Vinculos v
        JOIN H01Usuarios   u ON u.Id = v.UsuarioId
        LEFT JOIN H01Assinaturas a ON a.UsuarioId = u.Id
        LEFT JOIN H01Planos       p ON p.Id = a.PlanoId
        WHERE v.Canal = %s AND v.IdentificadorCanal = %s AND v.StatusConexao = 'conectado'
        ORDER BY a.CriadoEm DESC
        LIMIT 1
        """,
        (canal, str(identificador)),
    )

    if not row or row["status_usuario"] not in _STATUS_ATIVOS:
        _cache[chave] = None
        return None

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
        "limite_voz_seg": limite_voz,
        "limite_msgs_dia": limite_msgs,
    }
    tenant.update(get_config(tenant["usuario_id"]))
    _cache[chave] = tenant
    return tenant


def invalidate(canal: str, identificador: str):
    _cache.pop((canal, str(identificador)), None)


def vincular(token: str, canal: str, identificador: str, nome: str | None):
    """Consome um TokenVinculo de uso único e amarra o canal à conta.
    Retorna (ok: bool, mensagem: str)."""
    token = (token or "").strip()
    if not token:
        return False, "Código de vínculo vazio."

    identificador = str(identificador)
    canal_label = "WhatsApp" if canal == "whatsapp" else "Telegram"

    # O token pertence a uma linha (UsuarioId, Canal). Casar o canal evita consumir
    # um código de WhatsApp pelo Telegram (e vice-versa).
    vinc = db.query_one(
        """
        SELECT v.Id, v.UsuarioId, v.TokenExpiraEm, u.NomeCompleto, u.Status
        FROM H01Vinculos v
        JOIN H01Usuarios u ON u.Id = v.UsuarioId
        WHERE v.TokenVinculo = %s AND v.Canal = %s
        LIMIT 1
        """,
        (token, canal),
    )
    if not vinc:
        return False, "Código inválido. Gere um novo código no painel e tente de novo."

    if vinc["TokenExpiraEm"] and vinc["TokenExpiraEm"] < datetime.now():
        return False, "Esse código expirou. Gere um novo no painel."

    if vinc["Status"] not in _STATUS_ATIVOS:
        return False, "Sua conta não está ativa. Fale com o suporte."

    # Esse identificador já está conectado a OUTRA conta neste canal?
    outro = db.query_one(
        "SELECT UsuarioId FROM H01Vinculos "
        "WHERE Canal = %s AND IdentificadorCanal = %s AND UsuarioId <> %s LIMIT 1",
        (canal, identificador, vinc["UsuarioId"]),
    )
    if outro:
        return False, (
            f"Este {canal_label} já está conectado a outra conta. "
            "Desconecte-a primeiro no painel."
        )

    db.execute(
        """
        UPDATE H01Vinculos
           SET IdentificadorCanal = %s,
               NomeExibicao       = %s,
               StatusConexao      = 'conectado',
               TokenVinculo       = NULL,
               TokenExpiraEm      = NULL,
               DataVinculo        = %s
         WHERE Id = %s
        """,
        (identificador, nome, datetime.now(), vinc["Id"]),
    )
    ensure_config(vinc["UsuarioId"])
    invalidate(canal, identificador)
    log.info("%s %s vinculado ao usuário %s.", canal, identificador, vinc["UsuarioId"])
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
