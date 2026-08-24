-- migration_google_agenda.sql
-- Integração com a Google Agenda: tabela H01GoogleAgenda (1:1 por usuário) +
-- coluna GoogleEventId em H01Compromissos (id do evento espelhado no Google).
--
-- Rodar UMA vez no MySQL 8 (db_a43aea_hermes, Workbench SSL=No) ANTES de redeployar o
-- bot e o painel novos. Idempotente: re-rodar não quebra.

-- 1) Tabela de conexão com o Google (por usuário).
CREATE TABLE IF NOT EXISTS H01GoogleAgenda (
  UsuarioId     BIGINT       NOT NULL,
  RefreshToken  VARCHAR(512) NULL,
  CalendarId    VARCHAR(255) NULL,
  CalendarNome  VARCHAR(200) NULL,
  GoogleEmail   VARCHAR(200) NULL,
  StatusConexao VARCHAR(20)  NOT NULL DEFAULT 'desconectado',
  ConectadoEm   DATETIME     NULL,
  AtualizadoEm  DATETIME     NULL,
  PRIMARY KEY (UsuarioId),
  CONSTRAINT FK_H01GoogleAgenda_Usuario FOREIGN KEY (UsuarioId)
    REFERENCES H01Usuarios(Id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2) Coluna GoogleEventId em H01Compromissos (guarda com information_schema p/ ser idempotente).
SET @col := (SELECT COUNT(*) FROM information_schema.COLUMNS
             WHERE TABLE_SCHEMA = DATABASE()
               AND TABLE_NAME = 'H01Compromissos'
               AND COLUMN_NAME = 'GoogleEventId');
SET @sql := IF(@col = 0,
  'ALTER TABLE H01Compromissos ADD COLUMN GoogleEventId VARCHAR(255) NULL AFTER Avisado',
  'DO 0');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
