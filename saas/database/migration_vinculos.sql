-- ============================================================================
-- Migration: vínculo de canal genérico (H01Vinculos) — Fase 2 multi-canal.
--
-- Cria a tabela H01Vinculos (Canal + IdentificadorCanal) e COPIA os vínculos de
-- Telegram existentes (H01TelegramVinculos) para ela, para que quem já está
-- conectado siga funcionando SEM reconectar. Idempotente: re-rodar não duplica.
--
-- Rodar UMA vez no MySQL 8 (db_a43aea_hermes) ANTES de redeployar o bot novo E o
-- painel novo (ambos passam a usar H01Vinculos). A tabela antiga H01TelegramVinculos
-- é mantida como backup — pode ser removida depois, num cleanup separado.
--
-- Workbench: conectar com SSL = No.
-- ============================================================================

CREATE TABLE IF NOT EXISTS H01Vinculos (
  Id                 BIGINT       NOT NULL AUTO_INCREMENT,
  UsuarioId          BIGINT       NOT NULL,
  Canal              VARCHAR(20)  NOT NULL,
  IdentificadorCanal VARCHAR(64)  NULL,
  NomeExibicao       VARCHAR(100) NULL,
  StatusConexao      VARCHAR(20)  NOT NULL DEFAULT 'pendente',
  TokenVinculo       VARCHAR(64)  NULL,
  TokenExpiraEm      DATETIME     NULL,
  DataVinculo        DATETIME     NULL,
  PRIMARY KEY (Id),
  UNIQUE KEY UX_H01Vinculos_Canal_Ident (Canal, IdentificadorCanal),
  UNIQUE KEY UX_H01Vinculos_Usuario_Canal (UsuarioId, Canal),
  KEY IX_H01Vinculos_Token (TokenVinculo),
  CONSTRAINT FK_H01Vinculos_Usuario FOREIGN KEY (UsuarioId)
    REFERENCES H01Usuarios(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Copia os vínculos de Telegram existentes (só os que ainda não foram migrados).
INSERT INTO H01Vinculos
  (UsuarioId, Canal, IdentificadorCanal, NomeExibicao, StatusConexao, TokenVinculo, TokenExpiraEm, DataVinculo)
SELECT
  t.UsuarioId,
  'telegram',
  CAST(t.TelegramUserId AS CHAR),
  t.TelegramUsername,
  t.StatusConexao,
  t.TokenVinculo,
  t.TokenExpiraEm,
  t.DataVinculo
FROM H01TelegramVinculos t
WHERE NOT EXISTS (
  SELECT 1 FROM H01Vinculos v
  WHERE v.UsuarioId = t.UsuarioId AND v.Canal = 'telegram'
);
