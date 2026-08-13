using System.Security.Claims;
using HermesSaaS.Web.Data;
using HermesSaaS.Web.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages.Telegram;

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

    public TelegramVinculo? Vinculo { get; set; }
    public string BotUsername => _config["Telegram:BotUsername"] ?? "SeuBot";
    public bool Conectado => Vinculo?.StatusConexao == "conectado";
    public string? Token { get; set; }
    public DateTime? TokenExpiraEm { get; set; }

    private long Uid => long.Parse(User.FindFirstValue("UsuarioId") ?? "0");

    public async Task OnGetAsync()
    {
        Vinculo = await _db.TelegramVinculos.FirstOrDefaultAsync();
        // Reaproveita um token ainda válido; senão, mostra o botão p/ gerar.
        if (Vinculo?.TokenVinculo != null && Vinculo.TokenExpiraEm > DateTime.UtcNow)
        {
            Token = Vinculo.TokenVinculo;
            TokenExpiraEm = Vinculo.TokenExpiraEm;
        }
    }

    public async Task<IActionResult> OnPostGerarAsync()
    {
        await _onboarding.GerarTokenVinculoAsync(Uid);
        return RedirectToPage();
    }
}
