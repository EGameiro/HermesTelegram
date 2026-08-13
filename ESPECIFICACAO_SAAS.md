# Hermes SaaS — Especificação do Projeto

> Documento de referência que descreve o que é o produto, as funções do bot e a
> plataforma web (cadastro, painel e dados armazenados). Base para o desenvolvimento.

---

## 1. Visão geral

**O que é:** um **assistente pessoal por Telegram** (com voz) para **autônomos e pequenos
negócios**, oferecido como **SaaS multi-tenant**. O usuário conversa com o bot por texto ou
áudio e ele organiza a vida dele: lembra de compromissos, contas a pagar e de dar retorno a
clientes; responde perguntas; consulta clima e a internet.

**Problema que resolve:** profissionais perdem tempo, dinheiro e clientes por **esquecer** —
de responder uma mensagem, de dar um retorno prometido, de pagar uma conta, de um compromisso.

**Validação inicial (pesquisa, 64 respostas):** 64% já perderam/quase perderam cliente por
esquecimento; 44% perderam dinheiro ou cliente de fato; incômodo médio 4,3/5; 48% se
inscreveram para testar. Ponto de atenção: só 11% pagam por alguma ferramenta hoje — a
disposição a pagar ainda precisa ser validada (piloto + pré-venda).

**Escolha de canal e IA:** **Telegram** (gratuito, sem risco de ban, sem taxa por conversa) +
**Groq** (LLM rápido e barato na nuvem) ou **Ollama** (local). Isso mantém o custo por cliente
muito baixo (COGS estimado ~R$ 2–8/mês).

---

## 2. Como funciona (jornada do usuário)

1. A pessoa acessa o **site**, cria a conta e escolhe um **plano**.
2. Faz o **pagamento** (se plano pago) e **conecta o Telegram** (fluxo de vínculo seguro).
3. Passa a usar o **bot no Telegram**, por texto ou voz.
4. Gerencia tudo (plano, uso, configurações, dados) pelo **painel web**.

---

## 3. Funções do bot (o motor — já construído no protótipo)

| Função | Descrição |
|---|---|
| 💬 Conversa geral | Responde perguntas usando o LLM |
| 🕐 Data/hora reais | Injeta data/hora no fuso do usuário |
| 🌤️ Previsão do tempo | Open-Meteo (grátis); cidade configurável |
| 🌐 Busca na web | DuckDuckGo; responde com fontes |
| 💰 Contas a pagar | Cadastro por linguagem natural + confirmação; lembrete no vencimento; consulta por período com total |
| 🗓️ Compromissos com hora | Cadastro natural; aviso com antecedência configurável |
| 🎤 Entende voz | Transcrição (Whisper) — funciona em todos os recursos |
| 🗣️ Avisa por voz | Lembretes falados (TTS) |
| 🔀 LLM configurável | Ollama (local) ou Groq (nuvem) via variável |

**Comandos:** `/start`, `/reset`, `/contas`, `/pago`, `/remover`, `/lembretes`,
`/cancelar`, `/cidade`, `/id`, `/buscar`.

**Ideias futuras (discutidas, fora do MVP):** follow-up manual de pendências (encaminhar
mensagem → bot cobra depois); integração com WhatsApp (só via API oficial, formato assistente);
integração com Google Agenda.

---

## 4. Arquitetura SaaS (multi-tenant)

```
        Telegram (texto/voz)
             │ webhook
             ▼
   ┌──────────────┐   ┌────────┐   ┌──────────────────────┐
   │ Ingestão/API │──►│ Fila   │──►│ Workers (roteamento + │
   │ (identifica  │   │ (Redis)│   │ LLM + ferramentas)    │
   │  o tenant)   │   └────────┘   └──────────────────────┘
   └──────────────┘                          │
        ▲                                     ▼
   ┌──────────┐                 ┌──────────────────────────┐
   │ Scheduler│────────────────►│ Banco (MySQL 8,           │
   │ (varre   │                 │ multi-tenant): usuários,  │
   │ tenants) │                 │ planos, uso, contas,      │
   └──────────┘                 │ lembretes...              │
        │                       └──────────────────────────┘
        ▼                                     ▲
   Notificações           ┌───────────────────┴──────────┐
                          │ Site + Painel Web (cadastro, │
                          │ plano, config, faturas)      │
                          └──────────────────────────────┘
     LLM: Groq/Ollama   ·   Voz: OpenAI (Whisper + TTS)
```

**Princípios:**
- **Um app, muitos tenants** (nunca um container por cliente).
- **Workers sem estado** (escalam horizontalmente); estado no banco/Redis.
- **Roteamento de intenção em código** (regras), LLM para extrair/redigir/conversar.
- **Isolamento por tenant** em todas as queries (padrão do FaceRenew).

---

## 5. A parte WEB (site + painel)

### 5.1 Site público
- Página de vendas (proposta: "nunca mais esqueça de responder um cliente").
- Tabela de planos e preços.
- Cadastro / login (e-mail+senha; opcional login social).

### 5.2 Onboarding (cadastro + conexão do Telegram)
1. Criar conta (dados pessoais).
2. Escolher plano. **Na fase de teste, a ativação é MANUAL:** o admin ativa a conta e combina o
   pagamento por fora (ex: PIX). Gateway de pagamento automático fica para uma fase futura.
3. **Conectar o Telegram** — fluxo seguro por **token de vínculo de uso único**:
   - O painel gera um código curto e temporário.
   - O usuário abre o bot (link `t.me/seubot?start=<código>`) ou envia `/start <código>`.
   - O sistema amarra o **Telegram user_id** àquela conta.

### 5.3 Painel do cliente (área logada)
- **Dados pessoais** — ver/editar.
- **Plano e uso** — plano atual, consumo do mês (mensagens, minutos de voz), limite do plano,
  botão de **upgrade/downgrade**.
- **Conexão Telegram** — status (conectado/desconectado), reconectar, ver ID vinculado.
- **Configurações do assistente** — cidade padrão, voz on/off, horário dos lembretes,
  antecedência, PIN de segurança, fuso horário.
- **Meus dados do assistente** — espelho das contas a pagar e compromissos (visualizar/editar
  pela web, além do bot).
- **Faturas** — histórico de pagamentos, próxima cobrança, método de pagamento.
- **Conta** — trocar senha, **cancelar assinatura**, **excluir meus dados** (LGPD).

### 5.4 Painel administrativo (você, dono do SaaS)
- Lista de **clientes/tenants** (status, plano, data).
- **Uso e custo por cliente** (COGS real: tokens/voz) → margem por cliente.
- **Métricas do negócio**: MRR, churn, conversão trial→pago, nº de ativos.
- **Gestão de planos e preços**, cupons, contas em atraso.

---

## 6. Modelo de dados (o que fica guardado)

> Tudo com `tenant_id`/`usuario_id` e isolamento por linha. Abaixo, as entidades principais.

### 6.1 Usuário / Conta (tenant)
| Campo | Descrição |
|---|---|
| id | Identificador do tenant |
| nome_completo | Nome |
| email | Login / contato (único) |
| senha_hash | Senha (hash, nunca em texto) |
| telefone | Contato |
| documento | CPF/CNPJ (opcional, p/ nota fiscal) |
| criado_em, status | Cadastro e situação (ativo, trial, suspenso) |

### 6.2 Vínculo com o Telegram
| Campo | Descrição |
|---|---|
| telegram_user_id | **ID do Telegram** do dono (identidade autenticada) |
| telegram_username | @username (informativo) |
| status_conexao | conectado / pendente / desconectado |
| token_vinculo | **Token de uso único** e temporário (só no onboarding) |
| bot_token | **Só no Modelo B** (bot por cliente) — token do bot dele (guardar cifrado) |
| data_vinculo | Quando conectou |

> **Modelo A (recomendado p/ começar):** um bot para todos → guarda-se o `telegram_user_id`;
> **não há `bot_token` por cliente** (o token do bot é um segredo único do sistema).
> **Modelo B (white-label):** cada cliente tem o próprio bot → guarda-se também o `bot_token`
> (cifrado). Mais complexo (um polling/instância por token).

### 6.3 Assinatura / Plano
| Campo | Descrição |
|---|---|
| plano | free / pro / business |
| status | trial / ativo / cancelado / inadimplente |
| data_inicio, data_renovacao | Ciclo |
| ativacao_manual | true na fase de teste (admin ativa/define o plano na mão) |
| gateway_assinatura_id | ID no gateway — **futuro** (vazio enquanto a cobrança for manual) |

### 6.4 Pagamentos / Faturas
| id, valor, data, status, metodo, gateway_transacao_id |
|---|

> **Fase de teste:** registrado **manualmente** (o admin anota o pagamento combinado por fora).
> A cobrança automática via gateway entra numa fase futura.

### 6.5 Uso / Medição (por tenant, por mês) — base de custo e limites
| Campo | Descrição |
|---|---|
| tokens_llm | Tokens de IA consumidos |
| minutos_whisper | Minutos de áudio transcritos |
| caracteres_tts | Caracteres sintetizados em voz |
| qtd_mensagens | Volume de mensagens |
| custo_estimado | Convertido pela tabela de preços |

### 6.6 Configurações do assistente
| cidade, voz_ativa, hora_lembrete, antecedencia_min, pin, fuso |
|---|

### 6.7 Dados do assistente (as tabelas que o bot já usa, agora com tenant_id)
- **Contas a pagar**: descrição, valor, vencimento, pago, lembrete_enviado.
- **Compromissos**: descrição, quando (data+hora), avisado.
- **Histórico de conversa** (curto, para contexto).

### 6.8 Consentimento / LGPD
| aceite_termos, data_aceite, versao_termos |
|---|

---

## 7. Planos (rascunho — Telegram)

| Plano | Preço/mês | Inclui | Limites (fair-use) |
|---|---|---|---|
| **Grátis** | R$ 0 | Assistente completo (texto **e voz**): contas, lembretes, compromissos, clima | ~30 msgs/dia · **voz: 10 min/mês** |
| **Pro** | **R$ 24,99** | + busca web, resumo diário, follow-up manual, **voz ampla** | Volume alto |
| **Business** | **R$ 58,00** | + múltiplos usuários, integrações, relatórios, suporte | Custom |

> Preço **fixo** para o cliente + **medição interna** com fair-use para proteger a margem.
> Desconto anual (2 meses grátis). Trial de 14 dias.
> **Voz em todos os planos**, mas com **cota por plano** (grátis = pequena; pago = ampla) — a voz
> é o maior custo variável, então o limite do plano grátis precisa ser enxuto para não sangrar margem.

### 7.1 Limite de voz do plano Grátis (definido)
- **Cota: 10 minutos de áudio por mês** (soma dos minutos de áudio recebidos e transcritos — Whisper).
- Ao **esgotar a cota**, o bot avisa e passa a pedir **uso por texto** até virar o mês (o texto
  continua ilimitado dentro do limite de ~30 msgs/dia). Nada é bloqueado além da voz.
- A contagem reinicia no **1º dia de cada mês**.
- **Depende da medição de uso** (seção 6.5) — é ela que soma os minutos por tenant e aplica o corte.
- Valor **ajustável** por plano numa tabela de limites (não fixo no código).

---

## 8. Segurança e LGPD

- **Acesso:** identidade vem do **Telegram user_id autenticado** (no servidor), nunca do input;
  isolamento por tenant em todas as queries.
- **Onboarding:** vínculo por **token de uso único** (curto, temporário, descartável).
- **Reforço:** PIN no bot para ações sensíveis; recomendar 2FA do Telegram.
- **Segredos:** token(s) do bot e chaves de API em cofre/variáveis — nunca no código.
- **Dados:** criptografia em repouso, backups cifrados, privilégio mínimo, logs de auditoria.
- **Transparência (obrigatória):** bot do Telegram **não é ponta-a-ponta** (Telegram vê o
  tráfego); o **provedor de IA vê o conteúdo** da conversa no momento da resposta.
- **LGPD:** política de privacidade, consentimento no cadastro, direito de exclusão
  (`/apagar_meus_dados` + botão no painel), **DPA** com subprocessadores (Telegram, Groq/OpenAI,
  hospedagem, gateway de pagamento).

---

## 9. Stack sugerida

| Camada | Sugestão | Motivo |
|---|---|---|
| Bot / workers | **Python** | Reaproveita todo o código do protótipo |
| Fila | Redis | Simples, desacopla LLM lento |
| Banco | **MySQL 8** | Multi-tenant; mesmo banco do FaceRenew (Pomelo EF Core) |
| Site / Painel | **ASP.NET Core Razor** | Você já domina (FaceRenew) — mesmo padrão multi-tenant |
| LLM | Groq (nuvem) / Ollama (local) | Rápido e barato / privado |
| Voz | OpenAI (Whisper + TTS) | Preciso, sem carga na VPS |
| Pagamento | **Adiado** (manual na fase de teste) | Gateway (Mercado Pago/Asaas/Stripe) numa fase futura |
| Hospedagem | VPS + Dokploy | Já em uso |

---

## 10. Roadmap de desenvolvimento (fases)

**Fase 1 — Fundação multi-tenant (MVP)**
- Banco MySQL 8 multi-tenant; migrar o bot de SQLite/single-user para multi-tenant.
- Site + cadastro + login; onboarding com token de vínculo do Telegram.
- Planos + **ativação manual de plano pelo admin** + trial. (Gateway de pagamento fica p/ fase futura.)
- **Medição de uso** (tokens/voz por tenant) — base de custo e limites.
- Painel do cliente (dados, plano, config, conexão Telegram).

**Fase 2 — Operação e retenção**
- Painel administrativo (clientes, uso, métricas, MRR/churn).
- **Gateway de pagamento** (cobrança recorrente automática) + faturas.
- Limites de plano por fair-use; upgrade/downgrade.
- Follow-up manual de pendências; resumo diário.
- LGPD completo (política, exclusão, DPA).

**Fase 3 — Expansão**
- Integrações (Google Agenda); relatórios.
- (Avaliar) WhatsApp via API oficial (formato assistente).
- (Avaliar) white-label (Modelo B: bot por cliente).

---

## 11. Decisões (status)
1. ✅ **Modelo A (bot único)** — decidido. Identidade pelo `telegram_user_id`.
2. ✅ **Stack do site: ASP.NET Core Razor** — decidido (mesmo do FaceRenew).
3. ✅ **Gateway de pagamento: ADIADO** — controle manual na fase de teste; gateway numa fase futura.
4. ✅ **Preços definidos:** Pro R$ 24,99 · Business R$ 58,00 (Grátis R$ 0). Ainda a validar na pré-venda.
5. ✅ **Voz em todos os planos** — com cota de fair-use por plano (grátis pequena, pago ampla).
