# Hermes — Spike WhatsApp (UAZAPI)

Prova de conceito **isolada** pra testar o Hermes no WhatsApp via **UAZAPI**.
Não mexe no bot do Telegram nem no banco — só recebe uma mensagem no WhatsApp e
responde usando o Groq. Serve pra validar o canal antes de investir na integração real.

## Como funciona
```
WhatsApp → UAZAPI → (webhook) POST /webhook → parse → Groq → send_text → UAZAPI → WhatsApp
```

## Passos

1. **Deploy no Dokploy** como uma nova *Application*:
   - Repo `EGameiro/HermesTelegram`, Build Type **Dockerfile**, arquivo `saas/whatsapp-spike/Dockerfile`, context `saas/whatsapp-spike`.
   - **Domain** apontando a **porta 8080** (o Traefik faz o HTTPS). Ex.: `wa-spike.SEU-DOMINIO`.
   - **Environment:** copie de `.env.example` (UAZAPI_BASE_URL, UAZAPI_TOKEN, GROQ_API_KEY...).

2. **Aponte o webhook do UAZAPI** para:
   ```
   https://<seu-dominio-do-spike>/webhook
   ```
   (na instância UAZAPI, configure o Webhook URL para esse endereço).

3. **Teste:** mande uma mensagem no WhatsApp pro número conectado ao UAZAPI.
   - Olhe os **logs** do serviço no Dokploy: vai aparecer `WEBHOOK payload: {...}`.
   - Se o bot **não** responder, é porque o formato do payload/endpoint do seu UAZAPI
     é diferente do padrão — me mande esse `WEBHOOK payload` e o snippet de envio do
     Agente Clínica que eu ajusto `uazapi.py` (parse_incoming / send_text) na hora.

## Importante
- ⚠️ **1 número por instância.** Use um número de teste (não o de produção).
- Esta é a **fase 1 (spike)**. A fase 2 é unificar: um núcleo (cérebro + DB + agendador)
  com **adaptadores de canal** (Telegram + WhatsApp), pra o mesmo bot atender os dois.
