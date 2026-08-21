-- ============================================================================
-- Migração: limites de voz (Whisper) por plano
-- Banco: db_a43aea_hermes (MySQL 8 — SmartASP mysql8001.site4now.net)
-- Data: 2026-08-20
--
-- Define LimiteVozSegMes (segundos de ÁUDIO RECEBIDO por mês) no Pro e no
-- Business — antes estavam NULL (ilimitado), o que expunha o custo a abuso.
--   Pro      = 5.400 s  = 90 min/mês
--   Business = 12.000 s = 200 min/mês
--   Grátis   =   600 s  = 10 min/mês (inalterado)
--
-- Custo de referência (Whisper US$0,006/min, câmbio R$5,50): Pro ~R$3, Business ~R$6,60 no teto.
-- Idempotente: pode rodar mais de uma vez.
-- ============================================================================

UPDATE H01Planos SET LimiteVozSegMes = 5400  WHERE Codigo = 'pro';
UPDATE H01Planos SET LimiteVozSegMes = 12000 WHERE Codigo = 'business';
