-- ============================================================================
-- Migração: limites de volume (compromissos e contas) por usuário
-- Banco: db_a43aea_hermes (MySQL 8 — SmartASP mysql8001.site4now.net)
-- Data: 2026-08-20
--
-- Adiciona em H01Configuracoes:
--   LimiteCompromissos INT DEFAULT 100  -> máx. de compromissos EM ABERTO (Avisado=0)
--   LimiteContas       INT DEFAULT 300  -> máx. de contas (pagas ou não)
--
-- São independentes do teto de série (30) dos cadastros recorrentes.
-- As linhas existentes recebem o DEFAULT automaticamente.
-- MySQL 8 não suporta "ADD COLUMN IF NOT EXISTS"; se rodar 2x acusa duplicado (ignore).
-- ============================================================================

ALTER TABLE H01Configuracoes
  ADD COLUMN LimiteCompromissos INT NOT NULL DEFAULT 100 AFTER AntecedenciaMin,
  ADD COLUMN LimiteContas       INT NOT NULL DEFAULT 300 AFTER LimiteCompromissos;
