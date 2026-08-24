# Hermes SaaS — bot multi-tenant no WhatsApp

SaaS onde **cada usuário é um tenant**, atendido por um bot no **WhatsApp** (via UAZAPI),
com painel web em ASP.NET Core. **No ar e validado em runtime.** Ver a especificação completa
em [`../ESPECIFICACAO_SAAS.md`](../ESPECIFICACAO_SAAS.md).

> **Estado:** recebe e envia **texto e voz** no WhatsApp, multi-tenant, num processo único.
> Contas a pagar, compromissos, recorrentes, consultas e lembretes falados funcionam ponta a ponta.

## Estrutura

```
saas/
├── database/
│   └── schema.sql        ← schema MySQL 8 multi-tenant (contrato compartilhado)
├── bot/                  ← bot Python multi-tenant (WhatsApp)
│   ├── app.py            ← entrypoint (processo único): agendador + canal WhatsApp
│   ├── engine.py         ← NÚCLEO agnóstico de canal: intenções, extração, agendador, processar()
│   ├── llm.py            ← cérebro (Ollama/Groq), prompt com data/hora, histórico por tenant
│   ├── voice.py          ← voz agnóstica: Whisper (transcrever) + TTS (bytes↔texto)
│   ├── config.py         ← configuração (env) + helpers de fuso + FORCE_IPV4, num lugar só
│   ├── channels/         ← adaptador de canal sobre o núcleo
│   │   ├── base.py       ← contrato Channel/Sender + registro + Inbound + MsgContext
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
├── .env.example          ← variáveis (WhatsApp/UAZAPI, MySQL, LLM, voz)
└── web/                  ← painel ASP.NET Core Razor (NO AR no VPS)
    ├── Data/             ← AppUser, AppDbContext (H01* ExcludeFromMigrations), entidades,
    │                        CustomClaimsFactory, DatabaseSeeder, Migrations (só AspNet*)
    ├── Services/         ← OnboardingService (cadastro + token de vínculo), EmailService, BrTime
    ├── Pages/            ← Login (+Esqueci/Redefinir senha), Cadastro, Dashboard, Contas,
    │                        Compromissos, WhatsApp/Conectar, Conta/Configuracoes,
    │                        Conta (senha/cancelar/LGPD), Faturas, Admin/Clientes
    └── Dockerfile        ← imagem do painel (Kestrel :8080) p/ o VPS
```

## Decisões (da especificação)
- **Modelo A** (bot único): identidade pelo canal autenticado — o **telefone** do WhatsApp.
- Banco **MySQL 8** (mesmo do FaceRenew).
- Painel em **ASP.NET Core Razor**.
- Pagamento **manual** na fase de teste (ativação pelo admin).
- Voz em todos os planos; **grátis = 10 min/mês** (600 s).

## Arquitetura (núcleo agnóstico + canal WhatsApp)

O bot é um **núcleo agnóstico de canal** + um **adaptador** de WhatsApp, num **processo único**:

- **`engine.processar(inbound, sender)`** é o cérebro: recebe uma mensagem já normalizada
  (`Inbound`) e responde por um `Sender` — sem conhecer o canal concreto.
- **`channels/base.py`** define o contrato `Sender` (`send_text`/`send_typing`/`send_voice`/
  `baixar_audio`) e um **registro** (`sender_for(canal)`) que o agendador usa para entregar
  lembretes. A abstração segue genérica (permite novos canais no futuro), mas hoje **só o
  WhatsApp está ativo**.
- **`channels/whatsapp.py`** (webhook FastAPI/UAZAPI) normaliza a entrada e implementa o
  transporte. O canal sobe quando há `UAZAPI_BASE_URL`+`UAZAPI_TOKEN`; roda o servidor web na
  `PORT` (default 8080); um **único agendador** (thread) entrega os lembretes.

**Identidade (`H01Vinculos`):** tabela genérica **`H01Vinculos`** (`Canal` + `IdentificadorCanal`):
whatsapp → telefone (só dígitos). Um usuário tem **um vínculo por canal**. `tenants.resolve(canal,
identificador)` e `tenants.vincular(token, canal, identificador, nome)` operam sobre ela; o
agendador faz JOIN nela e entrega no canal conectado.

**Onboarding:** o painel gera um token numa linha `(UsuarioId, Canal)`
(`OnboardingService.GerarTokenVinculoAsync(uid, canal)`). O cliente **envia só o código** ao bot
no WhatsApp (`wa.me?text=<token>`) e o núcleo reconhece e vincula. Página: `Pages/WhatsApp/Conectar`.

**Contrato UAZAPI (WhatsApp), validado em runtime:**
- **Enviar texto:** `POST {BASE}/send/text` header `token`, body `{number, text}`.
- **Enviar voz (lembrete falado):** `POST {BASE}/send/media` body `{number, type:"ptt",
  file:"data:audio/ogg;base64,<b64>"}` — `ptt` = nota de voz (microfone). O TTS já gera OGG/Opus.
  Nota de voz não leva legenda → a legenda vai como texto separado.
- **Baixar áudio recebido:** `POST {BASE}/message/download` body `{id, return_base64:true}` →
  resposta com **`base64Data`** (não `base64`), `fileURL`, `mimetype`. Os bytes são transcritos
  pelo Whisper (`voice.transcrever`). *(O `GET /downloadMedia` do Agente Clínica é de uma versão
  antiga do UAZAPI e dá 404 nesta.)*
- **Webhook:** evento em `EventType=messages`, mensagem em `payload["message"]`; remetente em
  `sender_pn` (telefone real; `sender`=@lid, não usar); texto em `text`/`content`; tipo em
  `type`/`messageType`/`mediaType` (áudio = `audio`/`ptt`/`voice`); id em `id`/`messageid`.
  Ignora `fromMe`/`wasSentByApi`/`isGroup`. A instância pode não mandar URL direta → baixar por id.

## Integração com a Google Agenda (espelhamento de compromissos)

Mão única (**Hermes → Google**): todo compromisso agendado no bot vira um **evento** na
agenda Google do usuário. **Um evento por ocorrência** (recorrentes viram N eventos).

- **Painel** faz o **OAuth** (`Services/GoogleService.cs`, páginas `Pages/Google/Conectar` e
  `Pages/Google/Callback`): o usuário conecta a conta Google, o painel guarda o **RefreshToken**
  em `H01GoogleAgenda` e lista as agendas p/ ele **escolher** qual o Hermes alimenta (`CalendarId`).
  Escopos: `calendar.events` + `calendar.calendarlist.readonly` + `openid email`.
- **Bot** (`bot/gcal.py`): ao salvar um compromisso, troca o RefreshToken por um access token
  (cacheado) e cria o evento via Calendar API; guarda o `GoogleEventId` na linha do compromisso
  (`H01Compromissos.GoogleEventId`) p/ apagar no Google quando o usuário cancela. O espelhamento
  roda em **background thread** (não trava a resposta) e é **best-effort**: se o usuário não
  conectou, se o token foi revogado ou a API falhar, o Hermes segue normal (o lembrete pelo
  WhatsApp acontece do mesmo jeito).
- **Config (OAuth Client tipo Web, um só p/ painel e bot):** `Google__ClientId`/`Google__ClientSecret`
  no painel; `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` no bot. Redirect URI autorizado:
  `https://hermes.digiplay.net.br/Google/Callback` (+ `http://localhost:5034/Google/Callback` p/ dev).
  Enquanto o app OAuth estiver em **"Testing"**, funciona p/ até 100 test users sem verificação do Google.
- **Migração:** `database/migration_google_agenda.sql` (cria `H01GoogleAgenda` + coluna
  `GoogleEventId`). Rodar UMA vez antes de redeployar; idempotente.

## O banco (schema.sql)
Cada **usuário é um tenant**. Toda tabela de domínio tem `UsuarioId`, e toda query
**deve** filtrar por ele (isolamento — padrão `HasQueryFilter` do FaceRenew).

Tabelas (todas com prefixo **`H01`**):
`H01Usuarios`, **`H01Vinculos`** (vínculo de canal: `Canal`+`IdentificadorCanal`), `H01Planos`,
`H01Assinaturas`, `H01Pagamentos`, `H01UsoMensal`, `H01Configuracoes`, `H01ContasPagar`,
`H01Compromissos`, `H01HistoricoConversa`, **`H01GoogleAgenda`** (conexão com a Google Agenda).

> **Nota histórica:** a tabela `H01TelegramVinculos` foi substituída pela genérica `H01Vinculos`
> por [`database/migration_vinculos.sql`](database/migration_vinculos.sql) (já executada em
> produção). O script é mantido como registro; não precisa rodar de novo.

Aplicar (num MySQL 8):
```bash
mysql -u <user> -p < database/schema.sql
```

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
`AppUser` (role `Cliente`) + o `H01Vinculos` (canal whatsapp, pendente). Em seguida o usuário
gera um **token de vínculo** (curto, 30 min) e o **envia ao bot no WhatsApp** — fechando o ciclo.

**Rodar (dev):**
```bash
cd saas/web
# 1) aplicar o schema num MySQL 8 (uma vez): mysql -u <user> -p < ../database/schema.sql
# 2) ajustar ConnectionStrings:DefaultConnection no appsettings.Development.json (fora do git)
dotnet run
```
O `DatabaseSeeder` aplica a migration do Identity no startup e cria as roles + o admin
(`AdminSeed` no appsettings; padrão `admin@hermes.local` / `Admin@123` — trocar em produção).

### Deploy no VPS Dokploy (produção atual)

> **Por que NÃO SmartASP:** o plano shared tem **um único App Pool** (`egameiro-001`) em modo
> **ASP.NET 4.x / 32-bit**, compartilhado por 6 sites (um deles é .NET Framework, o que trava o pool
> em 4.x). ASP.NET Core **derruba o worker** do IIS (WAS "fatal communication error"), mesmo sozinho e
> out-of-process, e a **Rapid-Fail Protection** tira **todos os 6 sites** do ar. O app está 100% certo
> (sobe, conecta no MySQL, migrations OK — o stdout provou) — o problema é o IIS/pool, fora do nosso
> controle no plano. **Solução: Docker no VPS Dokploy** (Kestrel direto, sem IIS/ANCM/pool).

**Infra:** VPS Dokploy `75.119.139.224`. Banco: **MySQL 8 do SmartASP** `mysql8001.site4now.net` /
`db_a43aea_hermes` / user `a43aea_hermes` (o VPS conecta remoto, sem precisar liberar IP). O schema
`H01*` já está aplicado; o seeder cria as `AspNet*` no 1º start.

**Painel (.NET)** — `saas/web/Dockerfile` (multi-stage `sdk:8.0`→`aspnet:8.0`, Kestrel em `:8080`):
- Dokploy → **Application** → GitHub `EGameiro/HermesTelegram` `master` → Build Type **Dockerfile**
  (arquivo `saas/web/Dockerfile`, **context `saas/web`**).
- **Environment:** `ASPNETCORE_ENVIRONMENT=Production`,
  `ConnectionStrings__DefaultConnection=Server=mysql8001.site4now.net;Port=3306;Database=db_a43aea_hermes;User=a43aea_hermes;Password=***;AllowPublicKeyRetrieval=True;SslMode=None`,
  `AdminSeed__Senha=***`, `WhatsApp__BotNumber=<número do bot, só dígitos>`,
  `Google__ClientId=***`, `Google__ClientSecret=***` (integração Google Agenda).
- **Domains:** Container Port **8080** + um domínio (gerado via traefik.me/sslip.io ou próprio) → o
  **Traefik faz o HTTPS**.
- **Advanced → Volumes:** montar volume em **`/app/dp-keys`** (chaves de login estáveis entre redeploys).
- `Program.cs`: `UseForwardedHeaders` (atrás do Traefik, scheme https correto), versão MySQL **fixa
  `8.0.39`** (sem `AutoDetect`, que abria conexão no boot). `appsettings.json` versionado é placeholder
  (`localhost`); os segredos vêm das env vars do Dokploy.

**Layout no Dokploy (projetos separados, 1 serviço cada):**
- **`HermesTelegram`** = o **bot** (`saas/bot`) — roda o canal WhatsApp. *(O nome do projeto é
  histórico; o bot hoje é WhatsApp-only.)*
- **`HermesSite`** = o **painel** (.NET, `hermes.digiplay.net.br`).
- (o antigo `HermesWhats` era um spike de eco, **aposentado**.)

**Bot (Python)** — `saas/bot/Dockerfile` (`python:3.12-slim`), deploy via **docker-compose**
(`saas/docker-compose.yml`, serviço `bot`, sem ollama — LLM via Groq):
- **Environment:** `MYSQL_HOST`/`PORT`/`DB`/`USER`/`PASSWORD` (mesmo banco do painel);
  `LLM_PROVIDER=groq`, `GROQ_API_KEY=***`, `GROQ_MODEL=openai/gpt-oss-120b`; `OPENAI_API_KEY=***`
  (voz); `TZ=America/Sao_Paulo`; **`UAZAPI_BASE_URL`, `UAZAPI_TOKEN`** (obrigatórias — sem elas o
  bot não sobe); `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (opcionais — espelhamento na Google
  Agenda). `WA_DEBUG=1` só p/ diagnóstico.
- **Domain (webhook do WhatsApp):** o webhook precisa de um **Domain** → Service Name `bot`,
  Container Port **8080**. Domínio real **`hermesbot.digiplay.net.br`** (registro A no SmartASP DNS
  → `75.119.139.224`). ⚠️ **sslip.io não tem HTTPS válido** (Traefik faz 301→https sem cert) — use
  subdomínio próprio com Let's Encrypt. Webhook do UAZAPI → `https://hermesbot.digiplay.net.br/webhook`.
  O log de startup mostra `Canal ativo: WhatsApp`; `GET /` responde `{"ok":true,"service":"hermes-whatsapp"}`.
- ⚠️ **Um webhook por instância UAZAPI** — use uma instância separada da produção do Agente Clínica.

**Bot:** WhatsApp = a instância UAZAPI (`WhatsApp__BotNumber` no painel). O código (`saas/bot`) é o
"cérebro"; o vínculo é por `(Canal, IdentificadorCanal)` em `H01Vinculos`, então quem já vinculou
segue vinculado.

**Admin:** `admin@hermes.local` / `Admin@123`. ⚠️ O `AdminSeed__Senha` só vale na **1ª criação** — o
seeder **NÃO** atualiza a senha de um admin já existente. Trocar em *Minha conta → Alterar senha*.

**GitHub push:** o repo usa **Git Credential Manager**. Se o token expirar, o push num shell não-
interativo falha ("could not read Username"); rodar `git push` num terminal próprio abre o popup de
login e renova. Depois do push, dar **Redeploy** no serviço correspondente (painel e/ou bot).

## Como o bot funciona

**Fluxo de uma mensagem:** o adaptador `channels/whatsapp.py` normaliza o webhook num `Inbound`
`(canal, identificador, texto/voz)` e chama `engine.processar(inbound, sender)`. O núcleo resolve o
tenant, executa a intenção e responde pelo `sender` — **sem conhecer o canal concreto**.

**Resolução de tenant** (`tenants.resolve(canal, identificador)`): a identidade vem SEMPRE do
canal autenticado (nunca do texto). É procurada em `H01Vinculos` por `(Canal, IdentificadorCanal)`
com `StatusConexao='conectado'`, juntando `H01Usuarios` (status `trial`/`ativo`), `H01Assinaturas`
e `H01Planos`. Sem vínculo → o bot responde com o onboarding. Resultado cacheado em memória por
`(canal, identificador)`, invalidado no vínculo.

**Onboarding** (`tenants.vincular(token, canal, identificador, nome)`): valida o `TokenVinculo`
(não expirado, do mesmo canal), grava o `IdentificadorCanal`, seta `StatusConexao='conectado'`,
limpa o token e garante a linha de `H01Configuracoes`. O cliente **envia só o código** ao bot
(o núcleo reconhece uma palavra alfanumérica como token). `/id` funciona sem vínculo (suporte) e
devolve o identificador do canal.

**Isolamento**: `bills.*` e `reminders.*` recebem `usuario_id` e filtram por ele em toda query
(padrão `HasQueryFilter` do FaceRenew, aplicado à mão no SQL). O histórico de conversa em memória
é chaveado por `UsuarioId`.

**Voz (agnóstica, `voice.py`):** áudio recebido → o adaptador baixa (WhatsApp: `POST
/message/download`) → `voice.transcrever` (Whisper, pt-BR). Lembrete falado → `voice.tts`
(OpenAI TTS `gpt-4o-mini-tts`, OGG/Opus, normalizado por ffmpeg) → o adaptador envia (WhatsApp:
`POST /send/media` type `ptt`).

**Medição** (`usage.registrar`, upsert em `H01UsoMensal` por `UsuarioId+Ano+Mes`):
- **Tokens LLM** — `llm_chat` lê `total_tokens` (Groq) ou `prompt_eval_count+eval_count` (Ollama).
- **Segundos de voz** — duração do áudio recebido, medida antes de transcrever.
- **Caracteres TTS** — tamanho do texto falado nos lembretes.
- **Mensagens** — 1 por mensagem processada.

**Limite de voz** (`usage.voz_permitida`): antes de transcrever, compara `SegundosVoz` do mês
com `LimiteVozSegMes` do plano (grátis = 600s; pago tem teto). Estourou → o bot pede uso por
texto até virar o mês. Nada mais é bloqueado.

**Agendador multi-tenant**: varre a cada 60s. `bills.vencendo` e `reminders.due` respeitam
`HoraLembrete`/`AntecedenciaMin` de **cada tenant** (via `H01Configuracoes`) e fazem JOIN em
`H01Vinculos` — trazem `(canal, identificador)` do destino e `VozAtiva`. O `engine` entrega pelo
`sender_for(canal)`.

## Cadastro de conta pelo bot (regras)
Ao cadastrar uma conta a pagar por texto/voz, o bot **exige os três**: descrição, valor e
vencimento. Faltando qualquer um, ele **pede** o que falta e **não cadastra** (`extract_bill`
devolve `None` no campo ausente; `engine.processar` valida). Reconhece a intenção mesmo sem
número ("agendar pagamento", "cadastrar conta"…). Contas e compromissos **recorrentes** também
(ex.: "condomínio 600 todo dia 15 por 12 meses", "remédio de 8 em 8h por 5 dias"), com teto de
30 itens por série e limites de volume por usuário (`LimiteCompromissos`/`LimiteContas`).

## Rodar o bot localmente (dev)
1. Schema num MySQL 8 (uma vez): `mysql -u <user> -p < database/schema.sql`.
2. `cd saas/bot` → `python -m venv .venv` → `.venv\Scripts\activate` → `pip install -r requirements.txt`.
3. Setar env (`UAZAPI_BASE_URL`+`UAZAPI_TOKEN`, `MYSQL_*`, `LLM_PROVIDER=groq`, `GROQ_API_KEY`,
   `OPENAI_API_KEY`, `TZ`) e `python app.py`.

> Produção: ver **"Deploy no VPS Dokploy"**. ⚠️ Um **webhook por instância UAZAPI** — não aponte a
> mesma instância para o bot local **e** o do VPS ao mesmo tempo.

## Fluxo de vínculo (resumo)
1. Painel gera `TokenVinculo` (curto, com `TokenExpiraEm`) numa linha `(UsuarioId, Canal)` de
   `H01Vinculos` (`OnboardingService.GerarTokenVinculoAsync(uid, canal)`).
2. O usuário envia o token ao bot no WhatsApp: `wa.me/<numero>?text=<token>` ou digita só o código.
3. Bot valida o token (não expirado, mesmo canal), grava o `IdentificadorCanal` (telefone),
   seta `StatusConexao=conectado`.
4. A partir daí, mensagens daquele `(Canal, Identificador)` são atendidas como aquele tenant.
