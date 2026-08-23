using System.Security.Claims;
using HermesSaaS.Web.Data;
using HermesSaaS.Web.Services;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages;

public class DashboardModel : PageModel
{
    private readonly AppDbContext _db;
    private readonly IEmailService _email;
    private readonly UserManager<AppUser> _users;
    private readonly ILogger<DashboardModel> _log;

    public DashboardModel(AppDbContext db, IEmailService email, UserManager<AppUser> users, ILogger<DashboardModel> log)
    {
        _db = db;
        _email = email;
        _users = users;
        _log = log;
    }

    public Assinatura? Assinatura { get; set; }
    public Plano? Plano { get; set; }
    public Vinculo? Vinculo { get; set; }
    public UsoMensal? Uso { get; set; }
    public List<Plano> PlanosDisponiveis { get; set; } = new();

    public bool Conectado => Vinculo?.StatusConexao == "conectado";
    public int VozUsadaSeg => Uso?.SegundosVoz ?? 0;
    public int? VozLimiteSeg => Plano?.LimiteVozSegMes;
    public long Mensagens => Uso?.QtdMensagens ?? 0;
    public long Tokens => Uso?.TokensLlm ?? 0;

    public async Task OnGetAsync()
    {
        var uid = long.Parse(User.FindFirstValue("UsuarioId") ?? "0");

        Assinatura = await _db.Assinaturas.Include(a => a.Plano)
            .OrderByDescending(a => a.CriadoEm).FirstOrDefaultAsync();
        Plano = Assinatura?.Plano;
        Vinculo = await _db.Vinculos.FirstOrDefaultAsync(v => v.Canal == OnboardingService.CANAL_TELEGRAM);

        var agora = BrTime.Now;
        Uso = await _db.UsoMensal.FirstOrDefaultAsync(u => u.Ano == agora.Year && u.Mes == agora.Month);

        PlanosDisponiveis = await _db.Planos
            .Where(p => p.Codigo == "pro" || p.Codigo == "business")
            .OrderBy(p => p.PrecoMensal)
            .ToListAsync();
    }

    public async Task<IActionResult> OnPostAssinarAsync(string codigo)
    {
        var plano = await _db.Planos.FirstOrDefaultAsync(p => p.Codigo == codigo);
        if (plano is null || plano.PrecoMensal <= 0)
        {
            TempData["Erro"] = "Plano inválido.";
            return RedirectToPage();
        }

        var user = await _users.GetUserAsync(User);
        var nome = user?.NomeCompleto ?? User.FindFirstValue("NomeCompleto") ?? "(sem nome)";
        var mail = user?.Email ?? "(sem e-mail)";
        var uid = User.FindFirstValue("UsuarioId") ?? "?";

        var corpo = $@"<h2>Nova solicitação de assinatura — Hermes</h2>
<p><strong>Cliente:</strong> {nome}</p>
<p><strong>E-mail:</strong> {mail}</p>
<p><strong>UsuarioId (tenant):</strong> {uid}</p>
<p><strong>Plano escolhido:</strong> {plano.Nome} — R$ {plano.PrecoMensal:N2}/mês</p>
<hr/>
<p>Ative o plano em <strong>Admin → Clientes</strong>.</p>";

        try
        {
            await _email.EnviarAsync("eduardo@digiplay.net.br",
                $"[Hermes] {nome} quer assinar o plano {plano.Nome}", corpo);
        }
        catch (Exception ex)
        {
            // Não bloqueia nem expõe erro de SMTP ao cliente — só registra.
            _log.LogError(ex, "Falha ao enviar e-mail de solicitação de assinatura ({Plano})", plano.Codigo);
        }

        TempData["Ok"] = $"Recebemos seu interesse no plano {plano.Nome}! Ele será ativado em no máximo 24 horas. 🎉";
        return RedirectToPage();
    }
}
