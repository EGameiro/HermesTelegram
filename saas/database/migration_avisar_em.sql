-- ============================================================================
-- Migração: horário de aviso explícito para compromissos
-- Banco: db_a43aea_hermes (MySQL 8 — SmartASP mysql8001.site4now.net)
-- Data: 2026-08-20
--
-- Adiciona a coluna AvisarEm em H01Compromissos. Quando preenchida, o
-- agendador envia o lembrete EXATAMENTE nesse horário; quando NULL, usa a
-- AntecedenciaMin do usuário (comportamento antigo).
--
-- IMPORTANTE: rode ESTE script ANTES de subir a nova versão do bot.
-- O bot novo faz INSERT com a coluna AvisarEm e a query do agendador a lê —
-- se a coluna não existir, o cadastro de compromisso falha.
--
-- MySQL 8 não suporta "ADD COLUMN IF NOT EXISTS"; se rodar duas vezes vai
-- acusar "Duplicate column name 'AvisarEm'" — pode ignorar nesse caso.
-- ============================================================================

ALTER TABLE H01Compromissos
  ADD COLUMN AvisarEm DATETIME NULL AFTER Quando;
