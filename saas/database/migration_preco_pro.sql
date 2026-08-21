-- ============================================================================
-- Migração: preço do plano Pro
-- Banco: db_a43aea_hermes (MySQL 8 — SmartASP mysql8001.site4now.net)
-- Data: 2026-08-20
--
-- Ajusta a mensalidade do Pro de R$24,99 para R$27,40. Business permanece 58,00.
-- Idempotente.
-- ============================================================================

UPDATE H01Planos SET PrecoMensal = 27.40 WHERE Codigo = 'pro';
