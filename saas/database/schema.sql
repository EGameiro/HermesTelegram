-- ============================================================================
-- Hermes SaaS — Schema MySQL 8 (multi-tenant)
-- Contrato compartilhado entre o bot (Python) e o painel (.NET/EF Core).
-- Convenção: cada USUÁRIO é um TENANT. Toda tabela de domínio tem UsuarioId.
-- Charset utf8mb4 (emoji/acentos), engine InnoDB (FKs).
-- Prefixo de tabelas: "H01" (começa com letra -> não precisa de crase).
-- ============================================================================
-- Para criar do zero:  mysql -u <user> -p < schema.sql
-- ----------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS hermes_saas
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE hermes_saas;

-- ----------------------------------------------------------------------------
-- 1) Usuários / Contas (o TENANT)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS H01Usuarios (
  Id               BIGINT       NOT NULL AUTO_INCREMENT,
  NomeCompleto     VARCHAR(200) NOT NULL,
  Email            VARCHAR(200) NOT NULL,
  SenhaHash        VARCHAR(255) NULL,               -- gerenciada pelo painel (Identity)
  Telefone         VARCHAR(20)  NULL,
  Documento        VARCHAR(20)  NULL,               -- CPF/CNPJ (opcional, p/ NF)
  Status           VARCHAR(20)  NOT NULL DEFAULT 'trial', -- trial|ativo|suspenso|cancelado
  AceiteTermos     TINYINT(1)   NOT NULL DEFAULT 0,
  DataAceiteTermos DATETIME     NULL,
  VersaoTermos     VARCHAR(20)  NULL,
  CriadoEm         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  AtualizadoEm     DATETIME     NULL,
  PRIMARY KEY (Id),
  UNIQUE KEY UX_H01Usuarios_Email (Email)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 2) Vínculo com o Telegram (Modelo A: guarda o ID; Modelo B: guarda BotToken)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS H01TelegramVinculos (
  Id               BIGINT       NOT NULL AUTO_INCREMENT,
  UsuarioId        BIGINT       NOT NULL,
  TelegramUserId   BIGINT       NULL,               -- chat_id (identidade). Null até vincular.
  TelegramUsername VARCHAR(100) NULL,
  StatusConexao    VARCHAR(20)  NOT NULL DEFAULT 'pendente', -- pendente|conectado|desconectado
  TokenVinculo     VARCHAR(64)  NULL,               -- token de uso único (onboarding)
  TokenExpiraEm    DATETIME     NULL,
  DataVinculo      DATETIME     NULL,
  BotToken         VARCHAR(255) NULL,               -- SÓ Modelo B (guardar cifrado)
  PRIMARY KEY (Id),
  UNIQUE KEY UX_H01Telegram_UserId (TelegramUserId), -- um chat_id -> uma conta
  KEY IX_H01Telegram_Token (TokenVinculo),
  KEY IX_H01Telegram_Usuario (UsuarioId),
  CONSTRAINT FK_H01Telegram_Usuario FOREIGN KEY (UsuarioId)
    REFERENCES H01Usuarios(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 3) Catálogo de Planos (referência) + limites por plano
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS H01Planos (
  Id              INT          NOT NULL AUTO_INCREMENT,
  Codigo          VARCHAR(20)  NOT NULL,            -- free|pro|business
  Nome            VARCHAR(50)  NOT NULL,
  PrecoMensal     DECIMAL(10,2) NOT NULL DEFAULT 0,
  LimiteMsgsDia   INT          NULL,                -- null = sem limite
  LimiteVozSegMes INT          NULL,                -- cota de voz em segundos (null = ilimitado)
  Ativo           TINYINT(1)   NOT NULL DEFAULT 1,
  PRIMARY KEY (Id),
  UNIQUE KEY UX_H01Planos_Codigo (Codigo)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 4) Assinatura (plano atual do usuário)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS H01Assinaturas (
  Id                  BIGINT      NOT NULL AUTO_INCREMENT,
  UsuarioId           BIGINT      NOT NULL,
  PlanoId             INT         NOT NULL,
  Status              VARCHAR(20) NOT NULL DEFAULT 'trial', -- trial|ativo|cancelado|inadimplente
  AtivacaoManual      TINYINT(1)  NOT NULL DEFAULT 1,       -- true na fase de teste
  DataInicio          DATE        NOT NULL,
  DataRenovacao       DATE        NULL,
  TrialAte            DATE        NULL,
  GatewayAssinaturaId VARCHAR(100) NULL,                    -- futuro (gateway)
  CriadoEm            DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (Id),
  KEY IX_H01Assinaturas_Usuario (UsuarioId),
  CONSTRAINT FK_H01Assinatura_Usuario FOREIGN KEY (UsuarioId)
    REFERENCES H01Usuarios(Id) ON DELETE CASCADE,
  CONSTRAINT FK_H01Assinatura_Plano FOREIGN KEY (PlanoId)
    REFERENCES H01Planos(Id)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 5) Pagamentos / Faturas (registro manual na fase de teste)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS H01Pagamentos (
  Id                 BIGINT       NOT NULL AUTO_INCREMENT,
  UsuarioId          BIGINT       NOT NULL,
  Valor              DECIMAL(10,2) NOT NULL,
  Data               DATE         NOT NULL,
  Status             VARCHAR(20)  NOT NULL DEFAULT 'pago',  -- pago|pendente
  Metodo             VARCHAR(30)  NOT NULL DEFAULT 'pix',   -- pix|manual|cartao
  GatewayTransacaoId VARCHAR(100) NULL,
  Observacoes        VARCHAR(255) NULL,
  CriadoEm           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (Id),
  KEY IX_H01Pagamentos_Usuario (UsuarioId),
  CONSTRAINT FK_H01Pagamento_Usuario FOREIGN KEY (UsuarioId)
    REFERENCES H01Usuarios(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 6) Medição de uso (por usuário, por mês) — base de custo e limites (fair-use)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS H01UsoMensal (
  Id             BIGINT   NOT NULL AUTO_INCREMENT,
  UsuarioId      BIGINT   NOT NULL,
  Ano            SMALLINT NOT NULL,
  Mes            TINYINT  NOT NULL,
  TokensLlm      BIGINT   NOT NULL DEFAULT 0,       -- IA (Groq/OpenAI)
  SegundosVoz    INT      NOT NULL DEFAULT 0,       -- Whisper (áudio recebido)
  CaracteresTts  BIGINT   NOT NULL DEFAULT 0,       -- TTS (voz de saída)
  QtdMensagens   INT      NOT NULL DEFAULT 0,
  CustoEstimado  DECIMAL(10,4) NOT NULL DEFAULT 0,
  PRIMARY KEY (Id),
  UNIQUE KEY UX_H01Uso_Usuario_Mes (UsuarioId, Ano, Mes),
  CONSTRAINT FK_H01Uso_Usuario FOREIGN KEY (UsuarioId)
    REFERENCES H01Usuarios(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 7) Configurações do assistente (1:1 com o usuário)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS H01Configuracoes (
  UsuarioId       BIGINT      NOT NULL,
  Cidade          VARCHAR(100) NOT NULL DEFAULT 'Jacareí',
  VozAtiva        TINYINT(1)  NOT NULL DEFAULT 1,
  HoraLembrete    TINYINT     NOT NULL DEFAULT 8,   -- lembrete de contas
  AntecedenciaMin INT         NOT NULL DEFAULT 15,  -- aviso de compromissos
  Pin             VARCHAR(10) NULL,
  Fuso            VARCHAR(50) NOT NULL DEFAULT 'America/Sao_Paulo',
  PRIMARY KEY (UsuarioId),
  CONSTRAINT FK_H01Config_Usuario FOREIGN KEY (UsuarioId)
    REFERENCES H01Usuarios(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 8) Contas a pagar (domínio do assistente) — agora com UsuarioId
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS H01ContasPagar (
  Id               BIGINT       NOT NULL AUTO_INCREMENT,
  UsuarioId        BIGINT       NOT NULL,
  Descricao        VARCHAR(200) NOT NULL,
  Valor            DECIMAL(10,2) NULL,
  Vencimento       DATE         NOT NULL,
  Pago             TINYINT(1)   NOT NULL DEFAULT 0,
  LembreteEnviado  TINYINT(1)   NOT NULL DEFAULT 0,
  CriadoEm         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (Id),
  KEY IX_H01Contas_Usuario_Venc (UsuarioId, Vencimento),
  CONSTRAINT FK_H01Conta_Usuario FOREIGN KEY (UsuarioId)
    REFERENCES H01Usuarios(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 9) Compromissos com hora (lembretes) — agora com UsuarioId
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS H01Compromissos (
  Id          BIGINT       NOT NULL AUTO_INCREMENT,
  UsuarioId   BIGINT       NOT NULL,
  Descricao   VARCHAR(200) NOT NULL,
  Quando      DATETIME     NOT NULL,
  Avisado     TINYINT(1)   NOT NULL DEFAULT 0,
  CriadoEm    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (Id),
  KEY IX_H01Compromissos_Usuario_Quando (UsuarioId, Quando),
  CONSTRAINT FK_H01Compromisso_Usuario FOREIGN KEY (UsuarioId)
    REFERENCES H01Usuarios(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- 10) Histórico de conversa (curto, por usuário) — opcional; pode migrar p/ Redis
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS H01HistoricoConversa (
  Id         BIGINT      NOT NULL AUTO_INCREMENT,
  UsuarioId  BIGINT      NOT NULL,
  Papel      VARCHAR(20) NOT NULL,                  -- user|assistant|system
  Conteudo   TEXT        NOT NULL,
  CriadoEm   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (Id),
  KEY IX_H01Historico_Usuario (UsuarioId, CriadoEm),
  CONSTRAINT FK_H01Historico_Usuario FOREIGN KEY (UsuarioId)
    REFERENCES H01Usuarios(Id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ============================================================================
-- SEED: planos padrão (preços definidos; voz grátis = 10 min = 600 s)
-- ============================================================================
INSERT INTO H01Planos (Codigo, Nome, PrecoMensal, LimiteMsgsDia, LimiteVozSegMes, Ativo)
VALUES
  ('free',     'Grátis',   0.00, 30,   600,  1),   -- 10 min de voz/mês
  ('pro',      'Pro',     24.99, NULL, NULL, 1),   -- volume alto (fair-use no app)
  ('business', 'Business',58.00, NULL, NULL, 1)
ON DUPLICATE KEY UPDATE
  Nome=VALUES(Nome), PrecoMensal=VALUES(PrecoMensal),
  LimiteMsgsDia=VALUES(LimiteMsgsDia), LimiteVozSegMes=VALUES(LimiteVozSegMes);
