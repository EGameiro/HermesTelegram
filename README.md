# Hermes — Assistente pessoal no Telegram

Bot de Telegram self-hosted que funciona como assistente pessoal: conversa, consulta
previsão do tempo e a internet, gerencia contas a pagar e compromissos com lembretes
(inclusive por voz). O "cérebro" (LLM) roda **local** (Hermes 3 via Ollama, na VPS) ou
na **nuvem** (Groq), alternável por uma variável de ambiente.

---

## Funcionalidades

| Recurso | Como usar | Tecnologia |
|---|---|---|
| 💬 **Conversa geral** | Pergunte qualquer coisa | LLM (Ollama ou Groq) |
| 🕐 **Data/hora reais** | "que dia é hoje?" | Injeção de data/hora no prompt (fuso `TZ`) |
| 🌤️ **Previsão do tempo** | "previsão pra semana?" / `/cidade` | Open-Meteo (grátis, sem chave) |
| 🌐 **Busca na web** | `/buscar ...` ou "pesquise na internet..." | DuckDuckGo (`ddgs`) |
| 💰 **Contas a pagar** | "me lembra da conta de luz 100 dia 25" | SQLite + LLM p/ extração |
| 📊 **Total a pagar** | "quanto tenho pra pagar amanhã?" | Consulta por período |
| 🗓️ **Compromissos c/ hora** | "me avise amanhã às 9h da reunião" | SQLite + agendador |
| 🎤 **Entende voz** | Envie um áudio | Whisper (OpenAI) |
| 🗣️ **Avisa por voz** | Lembretes falados | TTS (OpenAI) |

Toda entrada por **texto ou áudio** funciona em todos os recursos. Cadastros de contas
e compromissos passam por uma etapa de **confirmação** ("sim/não") antes de salvar.

---

## Comandos

| Comando | Descrição |
|---|---|
| `/start`, `/help` | Ajuda |
| `/reset` | Apaga a memória da conversa |
| `/id` | Mostra seu chat_id (para `ALLOWED_CHAT_IDS`) |
| `/buscar <termo>` | Pesquisa na internet e responde com fontes |
| `/contas` | Lista suas contas a pagar (com total) |
| `/pago <nº ou nome>` | Marca uma conta como paga |
| `/remover <nº>` | Remove uma conta |
| `/lembretes` | Lista seus compromissos agendados |
| `/cancelar <nº>` | Cancela um compromisso |
| `/cidade <nome>` | Define sua cidade para a previsão do tempo |

Exemplos em linguagem natural:
- *"me lembra da conta de internet de 200 reais dia 10"*
- *"quanto tenho pra pagar essa semana?"*
- *"me avise amanhã às 9h da reunião com a Adriana"*
- *"quais meus compromissos para hoje?"*
- *"qual a previsão do tempo em Campos do Jordão?"*

---

## Arquitetura

```
                       ┌── Ollama (Hermes 3) na VPS   (LLM_PROVIDER=ollama)
Telegram ── bot Python ┤
   (voz)               └── Groq (nuvem, rápido)        (LLM_PROVIDER=groq)
        │
        ├── SQLite (contas + lembretes)   → volume bot_data:/data   [sempre na VPS]
        ├── Open-Meteo (clima) · DuckDuckGo (busca)
        └── OpenAI (Whisper STT + TTS)    [opcional, p/ voz]
```

- O bot faz **long polling** no Telegram (não precisa de domínio público).
- Um **agendador** roda em thread a cada 60s: avisa compromissos com antecedência e
  contas no dia do vencimento.
- O **banco de dados e todos os recursos** rodam na VPS. Com `LLM_PROVIDER=groq`, apenas
  a geração de texto vai para a nuvem (as mensagens da conversa passam pelo Groq; os dados
  guardados não saem da VPS).

### Roteamento de intenção
Decidir se uma mensagem é conta, compromisso, clima, busca ou papo é feito por **regras
em Python** (palavras-chave + regex), não pela IA — escolha por velocidade e
previsibilidade. O LLM só **extrai** dados (→ JSON), **redige** respostas com dados
buscados, e **conversa**.

### Módulos
| Arquivo | Responsabilidade |
|---|---|
| `bot/bot.py` | Núcleo: Telegram, roteamento, LLM, voz, agendador |
| `bot/weather.py` | Previsão do tempo (Open-Meteo) |
| `bot/websearch.py` | Busca na web (DuckDuckGo) |
| `bot/bills.py` | Contas a pagar (SQLite) |
| `bot/reminders.py` | Compromissos com hora (SQLite) |

---

## Variáveis de ambiente

### Essenciais
| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `TELEGRAM_TOKEN` | ✅ | — | Token do bot do @BotFather |
| `ALLOWED_CHAT_IDS` | ❌ | (vazio) | chat_ids autorizados, separados por vírgula. Vazio = liberado a todos |

### Provedor do LLM
| Variável | Padrão | Descrição |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` (local) ou `groq` (nuvem) |
| `OLLAMA_MODEL` | `hermes3:3b` | Modelo Ollama (ex: `hermes3:8b`) |
| `OLLAMA_MEM_LIMIT` | `5g` | Teto de RAM do container Ollama |
| `GROQ_API_KEY` | (vazio) | Chave do Groq (obrigatória se `LLM_PROVIDER=groq`) |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Modelo no Groq |
| `SYSTEM_PROMPT` | (ver compose) | Prompt de sistema |
| `MAX_HISTORY` | `12` | Nº de mensagens mantidas por conversa |
| `OLLAMA_TIMEOUT` | `300` | Timeout (s) da geração |

### Recursos
| Variável | Padrão | Descrição |
|---|---|---|
| `TZ` | `America/Sao_Paulo` | Fuso horário (usado em datas, lembretes, etc.) |
| `WEATHER_ENABLED` | `true` | Liga/desliga a previsão do tempo |
| `DEFAULT_CITY` | `Jacareí` | Cidade padrão da previsão |
| `WEBSEARCH_ENABLED` | `true` | Liga/desliga a busca na web |
| `BILLS_ENABLED` | `true` | Liga/desliga contas a pagar |
| `BILLS_DB` | `/data/bills.db` | Caminho do banco SQLite (no volume) |
| `REMINDER_HOUR` | `8` | Hora do dia p/ lembrete de contas |
| `REMINDERS_ENABLED` | `true` | Liga/desliga compromissos com hora |
| `REMINDER_LEAD_MIN` | `15` | Antecedência (min) do aviso de compromisso |

### Voz (opcional — OpenAI)
| Variável | Padrão | Descrição |
|---|---|---|
| `OPENAI_API_KEY` | (vazio) | Chave OpenAI. Vazio = voz desligada |
| `OPENAI_STT_MODEL` | `whisper-1` | Modelo de transcrição (áudio → texto) |
| `OPENAI_TTS_MODEL` | `tts-1` | Modelo de síntese (texto → voz) |
| `OPENAI_TTS_VOICE` | `nova` | Voz do TTS (`nova`, `onyx`, `alloy`, `shimmer`, `echo`, `fable`) |
| `REMINDER_VOICE` | `true` | Envia lembretes como áudio (fallback p/ texto) |

---

## Deploy no Dokploy

1. Suba este repositório no GitHub.
2. No Dokploy: **Create Service → Compose** → selecione o repo/branch `master`.
3. Em **Environment**, defina ao menos `TELEGRAM_TOKEN`. Para restringir o acesso,
   adicione `ALLOWED_CHAT_IDS` (descubra o seu enviando `/id` ao bot).
4. **Deploy** e mande `/start` ao bot.

### Usando o Ollama local (padrão)
Na primeira subida o bot baixa o modelo automaticamente (`hermes3:3b` ~2.5 GB; ou
`hermes3:8b` ~4.9 GB) — acompanhe os logs (`pull: ...`) até `Bot iniciado. Long polling...`.
O modelo fica num volume e não é re-baixado. Ollama descarrega o modelo da RAM após 10 min
ocioso (`OLLAMA_KEEP_ALIVE`).

### Usando o Groq (nuvem, mais rápido)
No Environment:
```
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
```
Deploy. O log mostra `Cérebro: GROQ (nuvem)`. O container Ollama fica ocioso (pode ser
mantido como fallback). Para voltar ao local: `LLM_PROVIDER=ollama` + Deploy.

### Voz
Para habilitar áudio (entrada e lembretes falados), adicione `OPENAI_API_KEY` no Environment.

---

## Persistência
Contas e compromissos ficam em SQLite no volume `bot_data` (`/data/bills.db`) — sobrevivem
a deploys e reinícios. O histórico de conversa e a cidade escolhida ficam em memória
(reiniciam a cada deploy).
