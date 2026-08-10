# Hermes no Telegram (Ollama + Dokploy)

Stack Docker Compose que roda o modelo **Hermes 3 (3B)** via **Ollama** e o expõe
através de um **bot de Telegram** — tudo self-hosted na VPS Dokploy, sem depender
de APIs externas.

## Arquitetura

```
Telegram  ──►  bot (Python)  ──►  ollama (hermes3:3b)  :11434
          ◄──                ◄──
```

- **ollama** — serve o modelo pela API HTTP interna (`:11434`). Não é exposto publicamente.
- **bot** — faz long polling no Telegram, encaminha o texto ao Ollama e devolve a resposta.
  Na primeira subida, baixa o modelo automaticamente (`/api/pull`).

Os dois containers conversam pela rede interna `hermes` do compose.

## Variáveis de ambiente

| Variável | Obrigatória | Padrão | Descrição |
|---|---|---|---|
| `TELEGRAM_TOKEN` | ✅ | — | Token do bot do @BotFather |
| `ALLOWED_CHAT_IDS` | ❌ | (vazio) | chat_ids autorizados, separados por vírgula. Vazio = liberado |
| `OLLAMA_MODEL` | ❌ | `hermes3:3b` | Modelo Ollama a usar |
| `SYSTEM_PROMPT` | ❌ | (ver compose) | Prompt de sistema |
| `MAX_HISTORY` | ❌ | `12` | Nº de mensagens mantidas por conversa |

## Comandos do bot

- `/start` ou `/help` — ajuda
- `/reset` — apaga a memória da conversa
- `/id` — mostra seu chat_id (útil p/ preencher `ALLOWED_CHAT_IDS`)

## Deploy no Dokploy

1. Suba este repositório no GitHub.
2. No Dokploy: **Create Service → Compose** → selecione o repo/branch.
3. Em **Environment**, cole ao menos `TELEGRAM_TOKEN=...`.
4. **Deploy**. A primeira subida baixa o modelo (~2.5 GB) — acompanhe pelos logs do
   container `bot` (mensagens `pull: ...`).
5. Mande `/start` ao bot no Telegram.

## Recursos

`hermes3:3b` em Q4 ocupa ~2.5 GB de RAM. O compose limita o Ollama a 5 GB
(`mem_limit`) e descarrega o modelo após 10 min ocioso (`OLLAMA_KEEP_ALIVE`),
para conviver com os outros apps da VPS (8 GB no total).
