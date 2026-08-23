using System.Security.Claims;
using HermesSaaS.Web.Data;
using HermesSaaS.Web.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages.WhatsApp;

public class ConectarModel : PageModel
{
    private readonly AppDbContext _db;
    private readonly OnboardingService _onboarding;
    private readonly IConfiguration _config;

    public ConectarModel(AppDbContext db, OnboardingService onboarding, IConfiguration config)
    {
        _db = db;
        _onboarding = onboarding;
        _config = config;
    }

    public Vinculo? Vinculo { get; set; }
    /// <summary>Número do bot de WhatsApp que o cliente adiciona/manda mensagem (só dígitos, E.164).</summary>
    public string BotNumero => _config["WhatsApp:BotNumber"] ?? "";
    public bool Conectado => Vinculo?.StatusConexao == "conectado";
    public string? Token { get; set; }
    public DateTime? TokenExpiraEm { get; set; }

    private long Uid => long.Parse(User.FindFirstValue("UsuarioId") ?? "0");

    public async Task OnGetAsync()
    {
        Vinculo = await _db.Vinculos.FirstOrDefaultAsync(v => v.Canal == OnboardingService.CANAL_WHATSAPP);
        if (Vinculo?.TokenVinculo != null && Vinculo.TokenExpiraEm > DateTime.UtcNow)
        {
            Token = Vinculo.TokenVinculo;
            TokenExpiraEm = Vinculo.TokenExpiraEm;
        }
    }

    public async Task<IActionResult> OnPostGerarAsync()
    {
        await _onboarding.GerarTokenVinculoAsync(Uid, OnboardingService.CANAL_WHATSAPP);
        return RedirectToPage();
    }
}
