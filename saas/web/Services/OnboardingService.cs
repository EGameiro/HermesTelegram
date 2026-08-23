using System.Security.Cryptography;
using HermesSaaS.Web.Data;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Services;

public record RegistroResultado(bool Sucesso, long UsuarioId, IEnumerable<string> Erros);

/// <summary>Cadastro de novo tenant (Usuario + Config + Assinatura trial + Vínculo) e
/// geração do token de vínculo do Telegram (onboarding).</summary>
public class OnboardingService
{
    public const string CANAL_TELEGRAM = "telegram";
    public const string CANAL_WHATSAPP = "whatsapp";

    private const string ROLE_CLIENTE = "Cliente";
    private const string VERSAO_TERMOS = "1.0";
    private const int TRIAL_DIAS = 14;
    private const int TOKEN_VALIDADE_MIN = 30;
    private const string TOKEN_ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"; // sem I/O/0/1

    private readonly AppDbContext _db;
    private readonly UserManager<AppUser> _users;

    public OnboardingService(AppDbContext db, UserManager<AppUser> users)
    {
        _db = db;
        _users = users;
    }

    /// <summary>Cria a conta (tenant) e o usuário de login, numa transação.</summary>
    public async Task<RegistroResultado> RegistrarAsync(
        string nomeCompleto, string email, string senha, bool aceiteTermos)
    {
        email = email.Trim().ToLowerInvariant();

        if (await _users.FindByEmailAsync(email) is not null)
            return new RegistroResultado(false, 0, new[] { "Já existe uma conta com esse e-mail." });

        var free = await _db.Planos.AsNoTracking().FirstOrDefaultAsync(p => p.Codigo == "free");
        if (free is null)
            return new RegistroResultado(false, 0, new[] { "Plano grátis não encontrado. Rode o schema.sql." });

        var hoje = DateOnly.FromDateTime(DateTime.UtcNow);
        await using var tx = await _db.Database.BeginTransactionAsync();

        var usuario = new Usuario
        {
            NomeCompleto = nomeCompleto.Trim(),
            Email = email,
            Status = "trial",
            AceiteTermos = aceiteTermos,
            DataAceiteTermos = aceiteTermos ? DateTime.UtcNow : null,
            VersaoTermos = aceiteTermos ? VERSAO_TERMOS : null,
            CriadoEm = DateTime.UtcNow,
        };
        _db.Usuarios.Add(usuario);
        await _db.SaveChangesAsync();  // materializa Usuario.Id

        _db.Configuracoes.Add(new Configuracao { UsuarioId = usuario.Id });
        _db.Vinculos.Add(new Vinculo
        {
            UsuarioId = usuario.Id,
            Canal = CANAL_TELEGRAM,
            StatusConexao = "pendente",
        });
        _db.Assinaturas.Add(new Assinatura
        {
            UsuarioId = usuario.Id,
            PlanoId = free.Id,
            Status = "trial",
            AtivacaoManual = true,
            DataInicio = hoje,
            TrialAte = hoje.AddDays(TRIAL_DIAS),
            CriadoEm = DateTime.UtcNow,
        });
        await _db.SaveChangesAsync();

        var appUser = new AppUser
        {
            UserName = email,
            Email = email,
            NomeCompleto = nomeCompleto.Trim(),
            UsuarioId = usuario.Id,
        };
        var res = await _users.CreateAsync(appUser, senha);
        if (!res.Succeeded)
        {
            await tx.RollbackAsync();
            return new RegistroResultado(false, 0, res.Errors.Select(e => e.Description));
        }

        if (!await _users.IsInRoleAsync(appUser, ROLE_CLIENTE))
            await _users.AddToRoleAsync(appUser, ROLE_CLIENTE);

        await tx.CommitAsync();
        return new RegistroResultado(true, usuario.Id, Array.Empty<string>());
    }

    /// <summary>Gera (ou renova) o token de vínculo de um canal do usuário logado.
    /// Retorna o token curto (Telegram: /start &lt;token&gt;; WhatsApp: enviar o código ao bot).</summary>
    public async Task<string> GerarTokenVinculoAsync(long usuarioId, string canal = CANAL_TELEGRAM)
    {
        var vinc = await _db.Vinculos.FirstOrDefaultAsync(v => v.UsuarioId == usuarioId && v.Canal == canal);
        if (vinc is null)
        {
            vinc = new Vinculo { UsuarioId = usuarioId, Canal = canal, StatusConexao = "pendente" };
            _db.Vinculos.Add(vinc);
        }

        var token = GerarToken(8);
        vinc.TokenVinculo = token;
        vinc.TokenExpiraEm = DateTime.UtcNow.AddMinutes(TOKEN_VALIDADE_MIN);
        await _db.SaveChangesAsync();
        return token;
    }

    private static string GerarToken(int tamanho)
    {
        var bytes = RandomNumberGenerator.GetBytes(tamanho);
        var chars = new char[tamanho];
        for (int i = 0; i < tamanho; i++)
            chars[i] = TOKEN_ALFABETO[bytes[i] % TOKEN_ALFABETO.Length];
        return new string(chars);
    }
}
