# Hermes SaaS — Desenvolvimento (Fase 1)

Transformação do bot single-tenant em **SaaS multi-tenant**. Ver a especificação
completa em [`../ESPECIFICACAO_SAAS.md`](../ESPECIFICACAO_SAAS.md).

## Estrutura

```
saas/
├── database/
│   └── schema.sql        ← schema MySQL 8 multi-tenant (contrato compartilhado)
├── bot/                  ← bot Python multi-tenant (Etapa 2 — feito)
│   ├── db.py             ← acesso ao MySQL (PyMySQL, conexão curta por operação)
│   ├── tenants.py        ← resolve tenant por TelegramUserId, vínculo por token, config
│   ├── usage.py          ← medição em H01UsoMensal + limite de voz (fair-use)
│   ├── bills.py          ← contas a pagar (H01ContasPagar), escopadas por UsuarioId
│   ├── reminders.py      ← compromissos (H01Compromissos), escopados por UsuarioId
│   ├── weather.py        ← previsão do tempo (Open-Meteo) — reaproveitado
│   ├── websearch.py      ← busca na web (DuckDuckGo) — reaproveitado
│   └── bot.py            ← long polling, roteamento, comandos, agendador multi-tenant
├── docker-compose.yml    ← stack SaaS (bot + Ollama; MySQL é externo)
├── .env.example          ← variáveis (Telegram, MySQL, LLM, voz)
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

Tabelas (todas com prefixo **`H01`**):
`H01Usuarios`, `H01TelegramVinculos`, `H01Planos`, `H01Assinaturas`, `H01Pagamentos`,
`H01UsoMensal`, `H01Configuracoes`, `H01ContasPagar`, `H01Compromissos`, `H01HistoricoConversa`.

Aplicar (num MySQL 8):
```bash
mysql -u <user> -p < database/schema.sql
```

## Ordem de construção (Fase 1)
1. ✅ **Schema MySQL** (`database/schema.sql`) — feito.
2. ✅ **Refatorar o bot p/ multi-tenant** (`bot/`) — feito. Ao receber mensagem, resolve o
   tenant por `TelegramUserId`; escopa contas/compromissos/config por `UsuarioId`; mede uso
   (tokens/voz/TTS/mensagens) em `H01UsoMensal`; aplica o **limite de voz** do plano.
3. ⬜ **Painel web (.NET)**: cadastro/login (Identity), onboarding com **token de vínculo**
   do Telegram, ativação manual de plano (admin), dados/plano/config do cliente.
4. ⬜ **Fluxo de onboarding ponta a ponta**: site gera token → usuário faz `/start <token>`
   no bot → vínculo criado → bot passa a atender.

## Como o bot multi-tenant funciona (Etapa 2)

**Resolução de tenant** (`tenants.resolve`): toda mensagem parte do `TelegramUserId`
autenticado (nunca do texto). Ele é procurado em `H01TelegramVinculos` (só `StatusConexao =
'conectado'`), junta `H01Usuarios` (status `trial`/`ativo`), `H01Assinaturas` e `H01Planos`.
Sem vínculo → o bot responde com as instruções de onboarding. Resultado é cacheado em memória
e invalidado no `/start`.

**Onboarding** (`/start <token>`): valida o `TokenVinculo` (não expirado), grava o
`TelegramUserId`/username, seta `StatusConexao = 'conectado'`, limpa o token e cria a linha
de `H01Configuracoes`. `/id` funciona sem vínculo (suporte).

**Isolamento**: `bills.*` e `reminders.*` recebem `usuario_id` e filtram por ele em toda query
(padrão `HasQueryFilter` do FaceRenew, aplicado à mão no SQL). O estado em memória
(histórico de conversa, confirmações pendentes) é chaveado por `UsuarioId`.

**Medição** (`usage.registrar`, upsert em `H01UsoMensal` por `UsuarioId+Ano+Mes`):
- **Tokens LLM** — `llm_chat` lê `total_tokens` (Groq) ou `prompt_eval_count+eval_count` (Ollama).
- **Segundos de voz** — `duration` do áudio do Telegram, medido antes de transcrever.
- **Caracteres TTS** — tamanho do texto falado nos lembretes.
- **Mensagens** — 1 por mensagem processada.

**Limite de voz** (`usage.voz_permitida`): antes de transcrever, compara `SegundosVoz` do mês
com `LimiteVozSegMes` do plano (grátis = 600s; pago = ilimitado). Estourou → o bot pede uso
por texto até virar o mês. Nada mais é bloqueado.

**Agendador multi-tenant**: varre a cada 60s. As queries `bills.vencendo` e `reminders.due`
respeitam a `HoraLembrete` e a `AntecedenciaMin` de **cada tenant** (via `H01Configuracoes`,
filtradas no SQL) e já trazem o `TelegramUserId` de destino e o `VozAtiva`.

## Rodar / deploy
1. Aplicar o schema num MySQL 8: `mysql -u <user> -p < database/schema.sql`.
2. Preencher `.env` a partir de `.env.example` (Telegram, MySQL, LLM, OpenAI).
3. Subir o stack `saas/docker-compose.yml` (no Dokploy: apontar para `saas/` e dar Deploy).

## Fluxo de vínculo (resumo)
1. Painel gera `TokenVinculo` (curto, com `TokenExpiraEm`) na `H01TelegramVinculos` do usuário.
2. Usuário abre `t.me/<bot>?start=<token>` ou envia `/start <token>`.
3. Bot valida o token (não expirado), grava o `TelegramUserId`, seta `StatusConexao=conectado`.
4. A partir daí, mensagens daquele `TelegramUserId` são atendidas como aquele tenant.
