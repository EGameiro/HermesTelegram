# Hermes SaaS — Desenvolvimento (Fase 1)

Transformação do bot single-tenant em **SaaS multi-tenant**. Ver a especificação
completa em [`../ESPECIFICACAO_SAAS.md`](../ESPECIFICACAO_SAAS.md).

## Estrutura

```
saas/
├── database/
│   └── schema.sql        ← schema MySQL 8 multi-tenant (contrato compartilhado)
├── bot/                  ← (a fazer) bot Python refatorado p/ multi-tenant
└── web/                  ← (a fazer) painel ASP.NET Core Razor
```

## Decisões (da especificação)
- **Modelo A** (bot único): identidade pelo `TelegramUserId` (chat_id).
- Banco **MySQL 8** (mesmo do FaceRenew).
- Painel em **ASP.NET Core Razor**.
- Pagamento **manual** na fase de teste (ativação pelo admin).
- Voz em todos os planos; **grátis = 10 min/mês** (600 s).

## O banco (schema.sql)
Cada **usuário é um tenant**. Toda tabela de domínio tem `UsuarioId`, e toda query
**deve** filtrar por ele (isolamento — padrão `HasQueryFilter` do FaceRenew).

Tabelas (todas com prefixo **`01`**; nome começa com dígito → usar crase no MySQL):
`01Usuarios`, `01TelegramVinculos`, `01Planos`, `01Assinaturas`, `01Pagamentos`,
`01UsoMensal`, `01Configuracoes`, `01ContasPagar`, `01Compromissos`, `01HistoricoConversa`.

Aplicar (num MySQL 8):
```bash
mysql -u <user> -p < database/schema.sql
```

## Ordem de construção (Fase 1)
1. ✅ **Schema MySQL** (`database/schema.sql`) — feito.
2. ⬜ **Refatorar o bot p/ multi-tenant**: ao receber mensagem, resolver o tenant por
   `TelegramUserId`; escopar contas/compromissos/config por `UsuarioId`; **medir uso**
   (tokens/voz) em `UsoMensal`; aplicar o **limite de voz** do plano grátis.
3. ⬜ **Painel web (.NET)**: cadastro/login (Identity), onboarding com **token de vínculo**
   do Telegram, ativação manual de plano (admin), dados/plano/config do cliente.
4. ⬜ **Fluxo de onboarding ponta a ponta**: site gera token → usuário faz `/start <token>`
   no bot → vínculo criado → bot passa a atender.

## Fluxo de vínculo (resumo)
1. Painel gera `TokenVinculo` (curto, com `TokenExpiraEm`) na `01TelegramVinculos` do usuário.
2. Usuário abre `t.me/<bot>?start=<token>` ou envia `/start <token>`.
3. Bot valida o token (não expirado), grava o `TelegramUserId`, seta `StatusConexao=conectado`.
4. A partir daí, mensagens daquele `TelegramUserId` são atendidas como aquele tenant.
