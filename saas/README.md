# Hermes SaaS — Desenvolvimento (Fase 1)

Transformação do bot single-tenant em **SaaS multi-tenant**. Ver a especificação
completa em [`../ESPECIFICACAO_SAAS.md`](../ESPECIFICACAO_SAAS.md).

## Estrutura

```
saas/
├── database/
│   └── schema.sql        ← schema MySQL 8 multi-tenant (contrato compartilhado)
├── bot/                  ← bot Python multi-tenant e MULTI-CANAL (Fase 2)
│   ├── app.py            ← entrypoint (processo único): agendador + Telegram + WhatsApp
│   ├── engine.py         ← NÚCLEO agnóstico de canal: intenções, extração, agendador, processar()
│   ├── llm.py            ← cérebro (Ollama/Groq), prompt com data/hora, histórico por tenant
│   ├── voice.py          ← voz agnóstica: Whisper (transcrever) + TTS (bytes↔texto)
│   ├── config.py         ← configuração (env) + helpers de fuso, num lugar só
│   ├── channels/         ← adaptadores de canal sobre o núcleo
│   │   ├── base.py       ← contrato Channel/Sender + registro + Inbound + MsgContext
│   │   ├── telegram.py   ← Telegram (long polling + transporte + download de voz)
│   │   └── whatsapp.py   ← WhatsApp/UAZAPI (webhook FastAPI + transporte + download de voz)
│   ├── db.py             ← acesso ao MySQL (PyMySQL + pool DBUtils)
│   ├── tenants.py        ← resolve tenant por (Canal, Identificador) em H01Vinculos, vínculo por token
│   ├── usage.py          ← medição em H01UsoMensal + limite de voz (fair-use)
│   ├── bills.py          ← contas a pagar (H01ContasPagar), escopadas por UsuarioId
│   ├── reminders.py      ← compromissos (H01Compromissos), escopados por UsuarioId
│   ├── weather.py        ← previsão do tempo (Open-Meteo) — reaproveitado
│   ├── websearch.py      ← busca na web (DuckDuckGo) — reaproveitado
│   └── Dockerfile        ← imagem do bot (python:3.12-slim) p/ o VPS
├── docker-compose.yml    ← compose do bot SaaS (só o bot; LLM via Groq; MySQL externo)
├── .env.example          ← variáveis (Telegram, MySQL, LLM, voz)
└── web/                  ← painel ASP.NET Core Razor (Etapa 3 — NO AR no VPS)
    ├── Data/             ← AppUser, AppDbContext (H01* ExcludeFromMigrations), entidades,
    │                        CustomClaimsFactory, DatabaseSeeder, Migrations (só AspNet*)
    ├── Services/         ← OnboardingService (cadastro + token de vínculo), EmailService, BrTime
    ├── Pages/            ← Login (+Esqueci/Redefinir senha), Cadastro, Dashboard, Contas,
    │                        Compromissos, Telegram/Conectar, Conta/Configuracoes, Conta
    │                        (senha/cancelar/LGPD), Faturas, Admin/Clientes
    └── Dockerfile        ← imagem do painel (Kestrel :8080) p/ o VPS
```

## Decisões (da especificação)
- **Modelo A** (bot único): identidade pelo `TelegramUserId` (chat_id).
- Banco **MySQL 8** (mesmo do FaceRenew).
- Painel em **ASP.NET Core Razor**.
- Pagamento **manual** na fase de teste (ativação pelo admin).
- Voz em todos os planos; **grátis = 10 min/mês** (600 s).

## Fase 2 — Arquitetura multi-canal (Telegram + WhatsApp)

O bot monolítico (`bot.py`) foi refatorado num **núcleo agnóstico de canal** + **adaptadores**,
tudo num **processo único**:

- **`engine.processar(inbound, sender)`** é o cérebro: recebe uma mensagem já normalizada
  (`Inbound`) e responde por um `Sender` — não sabe se é Telegram ou WhatsApp.
- **`channels/base.py`** define o contrato `Sender` (`send_text`/`send_typing`/`send_voice`/
  `baixar_audio`) e um **registro** (`sender_for(canal)`) que o agendador usa para entregar
  lembretes no canal certo.
- **`channels/telegram.py`** (long polling) e **`channels/whatsapp.py`** (webhook FastAPI/UAZAPI)
  normalizam a entrada e implementam o transporte. Cada canal é **independente** e opcional
  (liga por env): Telegram sobe se houver `TELEGRAM_TOKEN`; WhatsApp se houver
  `UAZAPI_BASE_URL`+`UAZAPI_TOKEN`. Com os dois ativos, o WhatsApp roda o servidor web (porta
  `PORT`, default 8080) e o Telegram roda numa thread; um **único agendador** atende ambos.

**Identidade multi-canal (`H01Vinculos`):** a antiga `H01TelegramVinculos` deu lugar à tabela
genérica **`H01Vinculos`** (`Canal` + `IdentificadorCanal`): telegram → TelegramUserId; whatsapp
→ telefone (só dígitos). Um usuário pode ter **um vínculo por canal**. `tenants.resolve(canal,
identificador)` e `tenants.vincular(token, canal, identificador, nome)` operam sobre ela; o
agendador faz JOIN nela e entrega em cada canal conectado. **Migração:** rodar
[`database/migration_vinculos.sql`](database/migration_vinculos.sql) UMA vez — cria a tabela e
**copia os vínculos de Telegram existentes** (quem já está conectado não reconecta).

**Onboarding por canal:** o painel gera um token numa linha `(UsuarioId, Canal)`
(`OnboardingService.GerarTokenVinculoAsync(uid, canal)`). No Telegram é `/start <token>`
(deep-link `t.me`); no WhatsApp o cliente **envia só o código** ao bot (`wa.me?text=<token>`) e
o núcleo reconhece e vincula. Páginas: `Pages/Telegram/Conectar` e `Pages/WhatsApp/Conectar`.

**Voz no WhatsApp:** áudio RECEBIDO é baixado (URL do webhook ou `GET /downloadMedia?id=`) e
transcrito por Whisper. Áudio ENVIADO (lembrete falado) ainda **não** tem contrato UAZAPI
provado → cai para **texto** (fallback do engine). Ligar TTS no WhatsApp é follow-up.

**Deploy da Fase 2 (bot + painel juntos):**
1. MySQL 8: rodar `database/migration_vinculos.sql`.
2. Redeploy do **painel** e do **bot** (ambos passam a usar `H01Vinculos`).
3. Para ligar o WhatsApp: criar/usar uma instância UAZAPI, setar `UAZAPI_BASE_URL`/`UAZAPI_TOKEN`
   no bot + mapear domínio → porta 8080, apontar o webhook do UAZAPI p/ `https://<dominio>/webhook`,
   e setar `WhatsApp:BotNumber` (número do bot) no painel.

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
3. ✅ **Painel web (.NET)** (`web/`) — login/cadastro (Identity), multi-tenancy por `UsuarioId`
   (claim + `HasQueryFilter`, padrão FaceRenew), onboarding com **token de vínculo**, dashboard
   (plano + uso do mês), **contas a pagar** e **compromissos** pela web (CRUD, espelho do bot),
   conexão do Telegram, configurações, **faturas**, **conta** (trocar senha / cancelar /
   excluir dados LGPD), e **ativação manual de plano** (admin, registra pagamento). Pendência
   menor: reset de senha por e-mail (SMTP).
4. ✅ **Fluxo de onboarding ponta a ponta** — funcionando: site gera token → `/start <token>` no bot →
   vínculo criado → bot atende como aquele tenant. **Painel e bot NO AR no VPS Dokploy**
   (ver "Deploy no VPS Dokploy"). Pendências menores: reset de senha por SMTP; botão "Desconectar"
   Telegram no painel (hoje desconecta-se limpando `H01TelegramVinculos` no banco).

## Painel web (.NET) — como funciona e rodar

**Arquitetura de auth/tenant:** o ASP.NET Identity (`AspNetUsers`) cuida do login; cada
`AppUser` aponta para um tenant `H01Usuarios` via `UsuarioId`. As tabelas `H01*` são o
contrato compartilhado com o bot, então o EF as mapeia com **`ExcludeFromMigrations`** (não as
cria nem altera) — a única migration do EF cria apenas as tabelas `AspNet*`. O `schema.sql`
continua sendo a fonte da verdade do domínio.

**Multi-tenancy:** após o login, a `CustomClaimsFactory` injeta o claim `UsuarioId`; o
`AppDbContext` lê esse claim e aplica `HasQueryFilter` por `UsuarioId` em todas as tabelas de
domínio — isolamento automático, igual ao `ClinicaId` do FaceRenew. O admin usa
`IgnoreQueryFilters()` para ver todos os clientes.

**Cadastro (onboarding):** `OnboardingService.RegistrarAsync` cria, numa transação,
`H01Usuarios` (trial) + `H01Configuracoes` + `H01Assinaturas` (plano free, 14 dias) + o
`AppUser` (role `Cliente`). Em seguida o usuário gera um **token de vínculo** (curto, 30 min) e
o envia como `/start <token>` ao bot — fechando o ciclo com a Etapa 2.

**Rodar (dev):**
```bash
cd saas/web
# 1) aplicar o schema num MySQL 8 (uma vez): mysql -u <user> -p < ../database/schema.sql
# 2) ajustar ConnectionStrings:DefaultConnection no appsettings.Development.json (fora do git)
dotnet run
```
O `DatabaseSeeder` aplica a migration do Identity no startup e cria as roles + o admin
(`AdminSeed` no appsettings; padrão `admin@hermes.local` / `Admin@123` — trocar em produção).

### Deploy no VPS Dokploy (produção atual — 14/08/2026)

> **Por que NÃO SmartASP:** o plano shared tem **um único App Pool** (`egameiro-001`) em modo
> **ASP.NET 4.x / 32-bit**, compartilhado por 6 sites (um deles é .NET Framework, o que trava o pool
> em 4.x). ASP.NET Core **derruba o worker** do IIS (WAS "fatal communication error"), mesmo sozinho e
> out-of-process, e a **Rapid-Fail Protection** tira **todos os 6 sites** do ar. O app está 100% certo
> (sobe, conecta no MySQL, migrations OK — o stdout provou) — o problema é o IIS/pool, fora do nosso
> controle no plano. O suporte do SmartASP confirmou: precisa de pool dedicado = **upgrade pago**.
> **Solução: Docker no VPS Dokploy** (Kestrel direto, sem IIS/ANCM/pool). Sobe limpo.

**Infra:** VPS Dokploy `75.119.139.224`. Banco: **MySQL 8 do SmartASP** `mysql8001.site4now.net` /
`db_a43aea_hermes` / user `a43aea_hermes` (o VPS conecta remoto, sem precisar liberar IP). O schema
`H01*` já está aplicado; o seeder cria as `AspNet*` no 1º start.

**Painel (.NET)** — `saas/web/Dockerfile` (multi-stage `sdk:8.0`→`aspnet:8.0`, Kestrel em `:8080`):
- Dokploy → **Application** → GitHub `EGameiro/HermesTelegram` `master` → Build Type **Dockerfile**
  (arquivo `saas/web/Dockerfile`, **context `saas/web`**).
- **Environment:** `ASPNETCORE_ENVIRONMENT=Production`,
  `ConnectionStrings__DefaultConnection=Server=mysql8001.site4now.net;Port=3306;Database=db_a43aea_hermes;User=a43aea_hermes;Password=***;AllowPublicKeyRetrieval=True;SslMode=None`,
  `AdminSeed__Senha=***`, `Telegram__BotUsername=digiplayhermesbot`.
- **Domains:** Container Port **8080** + um domínio (gerado via traefik.me/sslip.io ou próprio) → o
  **Traefik faz o HTTPS**.
- **Advanced → Volumes:** montar volume em **`/app/dp-keys`** (chaves de login estáveis entre redeploys).
- `Program.cs`: `UseForwardedHeaders` (atrás do Traefik, scheme https correto), versão MySQL **fixa
  `8.0.39`** (sem `AutoDetect`, que abria conexão no boot). `appsettings.json` versionado é placeholder
  (`localhost`); os segredos vêm das env vars do Dokploy.

**Bot (Python)** — `saas/bot/Dockerfile` (`python:3.12-slim`). Reaproveita o **serviço que já existia**
no projeto HermesTelegram do Dokploy (era o bot single-tenant `@HermesAssistente`, agora aposentado):
- **Compose Path** `saas/docker-compose.yml` (só o bot, **sem ollama** — LLM via Groq) **ou** Application
  com `saas/bot/Dockerfile` (context `saas/bot`).
- **Environment:** `TELEGRAM_TOKEN=<token do @DigiPlayHermes / digiplayhermesbot>`, `MYSQL_HOST`/`PORT`/
  `DB`/`USER`/`PASSWORD` (mesmo banco do painel), `LLM_PROVIDER=groq`, `GROQ_API_KEY=***`,
  `OPENAI_API_KEY=***` (voz, opcional), `TZ=America/Sao_Paulo`. **Sem domínio/porta** (é worker).
- ⚠️ **Um token por processo:** não rodar o `python bot.py` local e o serviço do VPS ao mesmo tempo com
  o mesmo token (conflito 409 no Telegram).

**Bot do SaaS = `@DigiPlayHermes` (`digiplayhermesbot`).** O código (`saas/bot`) é o "cérebro"; o token só
troca o "número". O vínculo é por **TelegramUserId** (mesmo em qualquer bot), então quem já vinculou
continua vinculado se trocar de bot.

**Admin:** `admin@hermes.local` / `Admin@123`. ⚠️ O `AdminSeed__Senha` só vale na **1ª criação** — o
seeder **NÃO** atualiza a senha de um admin já existente. Trocar em *Minha conta → Alterar senha*.

**GitHub push:** o repo usa **Git Credential Manager**. Se o token expirar, o push num shell não-
interativo falha ("could not read Username"); rodar `git push` num terminal próprio abre o popup de
login e renova. Depois do push, dar **Redeploy** no serviço correspondente (painel e/ou bot).

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

## Cadastro de conta pelo bot (regras)
Ao cadastrar uma conta a pagar por texto/voz, o bot **exige os três**: descrição, valor e
vencimento. Faltando qualquer um, ele **pede** o que falta e **não cadastra** (`extract_bill`
devolve `None` no campo ausente; `handle` valida). Reconhece a intenção mesmo sem número
("agendar pagamento", "cadastrar conta"…). No **eco** da voz (`🎤 Entendi:`), quando é cadastro
de conta, a **data é omitida** (aparece formatada só na confirmação `📝 Entendi`, `_echo_sem_data`).

## Rodar o bot localmente (dev)
1. Schema num MySQL 8 (uma vez): `mysql -u <user> -p < database/schema.sql`.
2. `cd saas/bot` → `python -m venv .venv` → `.venv\Scripts\activate` → `pip install -r requirements.txt`.
3. Setar env (`TELEGRAM_TOKEN` e/ou `UAZAPI_BASE_URL`+`UAZAPI_TOKEN`, `MYSQL_*`, `LLM_PROVIDER=groq`,
   `GROQ_API_KEY`, `OPENAI_API_KEY`, `TZ`) e `python app.py`.

> Produção: ver **"Deploy no VPS Dokploy"**. ⚠️ Não rode o bot local **e** o do VPS com o mesmo token
> ao mesmo tempo (conflito 409 no Telegram).

## Fluxo de vínculo (resumo)
1. Painel gera `TokenVinculo` (curto, com `TokenExpiraEm`) na `H01TelegramVinculos` do usuário.
2. Usuário abre `t.me/<bot>?start=<token>` ou envia `/start <token>`.
3. Bot valida o token (não expirado), grava o `TelegramUserId`, seta `StatusConexao=conectado`.
4. A partir daí, mensagens daquele `TelegramUserId` são atendidas como aquele tenant.
