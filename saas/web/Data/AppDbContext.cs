using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Identity.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Data;

public class AppDbContext : IdentityDbContext<AppUser>
{
    private readonly IHttpContextAccessor _http;

    public AppDbContext(DbContextOptions<AppDbContext> options, IHttpContextAccessor http)
        : base(options)
    {
        _http = http;
    }

    // Tabelas H01* (contrato compartilhado com o bot; NÃO migradas pelo EF).
    public DbSet<Usuario> Usuarios => Set<Usuario>();
    public DbSet<Vinculo> Vinculos => Set<Vinculo>();
    public DbSet<Plano> Planos => Set<Plano>();
    public DbSet<Assinatura> Assinaturas => Set<Assinatura>();
    public DbSet<Pagamento> Pagamentos => Set<Pagamento>();
    public DbSet<UsoMensal> UsoMensal => Set<UsoMensal>();
    public DbSet<Configuracao> Configuracoes => Set<Configuracao>();
    public DbSet<ContaPagar> ContasPagar => Set<ContaPagar>();
    public DbSet<Compromisso> Compromissos => Set<Compromisso>();
    public DbSet<GoogleAgenda> GoogleAgendas => Set<GoogleAgenda>();

    /// <summary>UsuarioId (tenant) do usuário logado, lido do claim. 0 = não autenticado
    /// (garante que os HasQueryFilter não vazem dados entre sessões).</summary>
    private long GetCurrentUsuarioId()
    {
        var user = _http.HttpContext?.User;
        if (user?.Identity?.IsAuthenticated == true)
        {
            var claim = user.FindFirst("UsuarioId");
            if (claim != null && long.TryParse(claim.Value, out var id))
                return id;
        }
        return 0;
    }

    protected override void OnModelCreating(ModelBuilder b)
    {
        base.OnModelCreating(b);

        b.Entity<AppUser>(e =>
        {
            e.Property(u => u.NomeCompleto).HasMaxLength(200);
        });

        b.Entity<Usuario>(e =>
        {
            e.ToTable("H01Usuarios", t => t.ExcludeFromMigrations());
            e.HasKey(u => u.Id);
            e.Property(u => u.NomeCompleto).HasMaxLength(200).IsRequired();
            e.Property(u => u.Email).HasMaxLength(200).IsRequired();
            e.Property(u => u.SenhaHash).HasMaxLength(255);
            e.Property(u => u.Telefone).HasMaxLength(20);
            e.Property(u => u.Documento).HasMaxLength(20);
            e.Property(u => u.Status).HasMaxLength(20);
            e.Property(u => u.VersaoTermos).HasMaxLength(20);
        });

        b.Entity<Vinculo>(e =>
        {
            e.ToTable("H01Vinculos", t => t.ExcludeFromMigrations());
            e.HasKey(v => v.Id);
            e.Property(v => v.Canal).HasMaxLength(20).IsRequired();
            e.Property(v => v.IdentificadorCanal).HasMaxLength(64);
            e.Property(v => v.NomeExibicao).HasMaxLength(100);
            e.Property(v => v.StatusConexao).HasMaxLength(20);
            e.Property(v => v.TokenVinculo).HasMaxLength(64);
            e.HasQueryFilter(v => v.UsuarioId == GetCurrentUsuarioId());
        });

        b.Entity<Plano>(e =>
        {
            e.ToTable("H01Planos", t => t.ExcludeFromMigrations());
            e.HasKey(p => p.Id);
            e.Property(p => p.Codigo).HasMaxLength(20);
            e.Property(p => p.Nome).HasMaxLength(50);
            e.Property(p => p.PrecoMensal).HasPrecision(10, 2);
        });

        b.Entity<Assinatura>(e =>
        {
            e.ToTable("H01Assinaturas", t => t.ExcludeFromMigrations());
            e.HasKey(a => a.Id);
            e.Property(a => a.Status).HasMaxLength(20);
            e.Property(a => a.GatewayAssinaturaId).HasMaxLength(100);
            e.HasOne(a => a.Plano).WithMany().HasForeignKey(a => a.PlanoId);
            e.HasQueryFilter(a => a.UsuarioId == GetCurrentUsuarioId());
        });

        b.Entity<Pagamento>(e =>
        {
            e.ToTable("H01Pagamentos", t => t.ExcludeFromMigrations());
            e.HasKey(p => p.Id);
            e.Property(p => p.Valor).HasPrecision(10, 2);
            e.Property(p => p.Status).HasMaxLength(20);
            e.Property(p => p.Metodo).HasMaxLength(30);
            e.Property(p => p.GatewayTransacaoId).HasMaxLength(100);
            e.Property(p => p.Observacoes).HasMaxLength(255);
            e.HasQueryFilter(p => p.UsuarioId == GetCurrentUsuarioId());
        });

        b.Entity<UsoMensal>(e =>
        {
            e.ToTable("H01UsoMensal", t => t.ExcludeFromMigrations());
            e.HasKey(u => u.Id);
            e.Property(u => u.CustoEstimado).HasPrecision(10, 4);
            e.HasQueryFilter(u => u.UsuarioId == GetCurrentUsuarioId());
        });

        b.Entity<Configuracao>(e =>
        {
            e.ToTable("H01Configuracoes", t => t.ExcludeFromMigrations());
            e.HasKey(c => c.UsuarioId);
            e.Property(c => c.UsuarioId).ValueGeneratedNever();
            e.Property(c => c.Cidade).HasMaxLength(100);
            e.Property(c => c.Pin).HasMaxLength(10);
            e.Property(c => c.Fuso).HasMaxLength(50);
            e.HasQueryFilter(c => c.UsuarioId == GetCurrentUsuarioId());
        });

        b.Entity<ContaPagar>(e =>
        {
            e.ToTable("H01ContasPagar", t => t.ExcludeFromMigrations());
            e.HasKey(c => c.Id);
            e.Property(c => c.Descricao).HasMaxLength(200).IsRequired();
            e.Property(c => c.Valor).HasPrecision(10, 2);
            e.HasQueryFilter(c => c.UsuarioId == GetCurrentUsuarioId());
        });

        b.Entity<Compromisso>(e =>
        {
            e.ToTable("H01Compromissos", t => t.ExcludeFromMigrations());
            e.HasKey(c => c.Id);
            e.Property(c => c.Descricao).HasMaxLength(200).IsRequired();
            e.Property(c => c.GoogleEventId).HasMaxLength(255);
            e.HasQueryFilter(c => c.UsuarioId == GetCurrentUsuarioId());
        });

        b.Entity<GoogleAgenda>(e =>
        {
            e.ToTable("H01GoogleAgenda", t => t.ExcludeFromMigrations());
            e.HasKey(g => g.UsuarioId);
            e.Property(g => g.UsuarioId).ValueGeneratedNever();
            e.Property(g => g.RefreshToken).HasMaxLength(512);
            e.Property(g => g.CalendarId).HasMaxLength(255);
            e.Property(g => g.CalendarNome).HasMaxLength(200);
            e.Property(g => g.GoogleEmail).HasMaxLength(200);
            e.Property(g => g.StatusConexao).HasMaxLength(20);
            e.HasQueryFilter(g => g.UsuarioId == GetCurrentUsuarioId());
        });
    }
}
