namespace HermesSaaS.Web.Data;

// Entidades mapeadas às tabelas H01* já criadas por saas/database/schema.sql
// (contrato compartilhado com o bot Python). O EF NÃO gera/migra essas tabelas
// (ExcludeFromMigrations no AppDbContext) — só as lê/escreve.

/// <summary>Usuário/conta = TENANT. Espelha dados de contato/status também lidos pelo bot.</summary>
public class Usuario
{
    public long Id { get; set; }
    public string NomeCompleto { get; set; } = string.Empty;
    public string Email { get; set; } = string.Empty;
    public string? SenhaHash { get; set; }          // auth fica no AspNetUsers; aqui é opcional
    public string? Telefone { get; set; }
    public string? Documento { get; set; }
    public string Status { get; set; } = "trial";   // trial|ativo|suspenso|cancelado
    public bool AceiteTermos { get; set; }
    public DateTime? DataAceiteTermos { get; set; }
    public string? VersaoTermos { get; set; }
    public DateTime CriadoEm { get; set; } = DateTime.UtcNow;
    public DateTime? AtualizadoEm { get; set; }
}

/// <summary>Vínculo de canal. Identidade = IdentificadorCanal por Canal:
/// whatsapp -> telefone (só dígitos). Um por (usuário, canal).</summary>
public class Vinculo
{
    public long Id { get; set; }
    public long UsuarioId { get; set; }
    public string Canal { get; set; } = "whatsapp";          // whatsapp
    public string? IdentificadorCanal { get; set; }          // telefone (só dígitos)
    public string? NomeExibicao { get; set; }                // username / pushname
    public string StatusConexao { get; set; } = "pendente";  // pendente|conectado|desconectado
    public string? TokenVinculo { get; set; }
    public DateTime? TokenExpiraEm { get; set; }
    public DateTime? DataVinculo { get; set; }
}

/// <summary>Catálogo de planos (referência). Semeado pelo schema.sql.</summary>
public class Plano
{
    public int Id { get; set; }
    public string Codigo { get; set; } = string.Empty;       // free|pro|business
    public string Nome { get; set; } = string.Empty;
    public decimal PrecoMensal { get; set; }
    public int? LimiteMsgsDia { get; set; }
    public int? LimiteVozSegMes { get; set; }
    public bool Ativo { get; set; } = true;
}

/// <summary>Assinatura (plano atual do usuário).</summary>
public class Assinatura
{
    public long Id { get; set; }
    public long UsuarioId { get; set; }
    public int PlanoId { get; set; }
    public string Status { get; set; } = "trial";            // trial|ativo|cancelado|inadimplente
    public bool AtivacaoManual { get; set; } = true;
    public DateOnly DataInicio { get; set; }
    public DateOnly? DataRenovacao { get; set; }
    public DateOnly? TrialAte { get; set; }
    public string? GatewayAssinaturaId { get; set; }
    public DateTime CriadoEm { get; set; } = DateTime.UtcNow;

    public Plano? Plano { get; set; }
}

/// <summary>Pagamentos/faturas (registro manual na fase de teste).</summary>
public class Pagamento
{
    public long Id { get; set; }
    public long UsuarioId { get; set; }
    public decimal Valor { get; set; }
    public DateOnly Data { get; set; }
    public string Status { get; set; } = "pago";             // pago|pendente
    public string Metodo { get; set; } = "pix";              // pix|manual|cartao
    public string? GatewayTransacaoId { get; set; }
    public string? Observacoes { get; set; }
    public DateTime CriadoEm { get; set; } = DateTime.UtcNow;
}

/// <summary>Medição de uso por mês (COGS + limites). Gravada pelo bot; lida pelo painel.</summary>
public class UsoMensal
{
    public long Id { get; set; }
    public long UsuarioId { get; set; }
    public short Ano { get; set; }
    public byte Mes { get; set; }
    public long TokensLlm { get; set; }
    public int SegundosVoz { get; set; }
    public long CaracteresTts { get; set; }
    public int QtdMensagens { get; set; }
    public decimal CustoEstimado { get; set; }
}

/// <summary>Configurações do assistente (1:1 com o usuário). PK = UsuarioId.</summary>
public class Configuracao
{
    public long UsuarioId { get; set; }
    public string Cidade { get; set; } = "Jacareí";
    public bool VozAtiva { get; set; } = true;
    public byte HoraLembrete { get; set; } = 8;
    public int AntecedenciaMin { get; set; } = 15;
    public int LimiteCompromissos { get; set; } = 100;   // compromissos em aberto
    public int LimiteContas { get; set; } = 300;         // contas (pagas ou não)
    public string? Pin { get; set; }
    public string Fuso { get; set; } = "America/Sao_Paulo";
}

/// <summary>Conta a pagar do assistente (espelho do que o bot cadastra).</summary>
public class ContaPagar
{
    public long Id { get; set; }
    public long UsuarioId { get; set; }
    public string Descricao { get; set; } = string.Empty;
    public decimal? Valor { get; set; }
    public DateOnly Vencimento { get; set; }
    public bool Pago { get; set; }
    public bool LembreteEnviado { get; set; }
    public DateTime CriadoEm { get; set; } = DateTime.UtcNow;
}

/// <summary>Compromisso com hora marcada (espelho do que o bot agenda).</summary>
public class Compromisso
{
    public long Id { get; set; }
    public long UsuarioId { get; set; }
    public string Descricao { get; set; } = string.Empty;
    public DateTime Quando { get; set; }
    public bool Avisado { get; set; }
    public string? GoogleEventId { get; set; }       // id do evento espelhado na Google Agenda
    public DateTime CriadoEm { get; set; } = DateTime.UtcNow;
}

/// <summary>Conexão com a Google Agenda (1:1 com o usuário). PK = UsuarioId. O painel
/// faz o OAuth e guarda o RefreshToken; o bot usa p/ espelhar os compromissos.</summary>
public class GoogleAgenda
{
    public long UsuarioId { get; set; }
    public string? RefreshToken { get; set; }
    public string? CalendarId { get; set; }          // 'primary' ou id/e-mail da agenda escolhida
    public string? CalendarNome { get; set; }        // nome amigável (exibição)
    public string? GoogleEmail { get; set; }         // conta Google conectada (exibição)
    public string StatusConexao { get; set; } = "desconectado"; // conectado|desconectado
    public DateTime? ConectadoEm { get; set; }
    public DateTime? AtualizadoEm { get; set; }
}
