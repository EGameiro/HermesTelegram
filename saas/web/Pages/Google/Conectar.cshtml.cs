using System.Security.Claims;
using System.Security.Cryptography;
using HermesSaaS.Web.Data;
using HermesSaaS.Web.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages.Google;

public class ConectarModel : PageModel
{
    private readonly AppDbContext _db;
    private readonly GoogleService _google;

    public ConectarModel(AppDbContext db, GoogleService google)
    {
        _db = db;
        _google = google;
    }

    public GoogleAgenda? Conta { get; set; }
    public bool Configurado => _google.Configurado;
    public bool Conectado => Conta?.StatusConexao == "conectado";
    public List<GoogleCalendar> Agendas { get; set; } = new();
    public bool FalhaAoListar { get; set; }

    private long Uid => long.Parse(User.FindFirstValue("UsuarioId") ?? "0");
    private string RedirectUri => $"{Request.Scheme}://{Request.Host}/Google/Callback";

    public async Task OnGetAsync()
    {
        Conta = await _db.GoogleAgendas.FirstOrDefaultAsync();
        if (Conectado && !string.IsNullOrEmpty(Conta!.RefreshToken))
        {
            var token = await _google.AccessTokenFromRefreshAsync(Conta.RefreshToken);
            if (token is null)
                FalhaAoListar = true;   // token revogado/expirado -> oferecer reconectar
            else
                Agendas = await _google.ListCalendarsAsync(token);
        }
    }

    public IActionResult OnPostConectar()
    {
        if (!_google.Configurado)
        {
            TempData["Erro"] = "A integração com o Google ainda não foi configurada. Fale com o suporte.";
            return RedirectToPage();
        }
        var state = Convert.ToHexString(RandomNumberGenerator.GetBytes(16));
        TempData["gstate"] = state;
        return Redirect(_google.BuildAuthUrl(RedirectUri, state));
    }

    public async Task<IActionResult> OnPostSelecionarAsync(string calendarId, string calendarNome)
    {
        var conta = await _db.GoogleAgendas.FirstOrDefaultAsync();
        if (conta is null || conta.StatusConexao != "conectado")
        {
            TempData["Erro"] = "Conecte sua conta Google primeiro.";
            return RedirectToPage();
        }
        conta.CalendarId = calendarId;
        conta.CalendarNome = calendarNome;
        conta.AtualizadoEm = DateTime.UtcNow;
        await _db.SaveChangesAsync();
        TempData["Ok"] = $"Pronto! O Hermes vai lançar os compromissos na agenda \"{calendarNome}\".";
        return RedirectToPage();
    }

    public async Task<IActionResult> OnPostDesconectarAsync()
    {
        var conta = await _db.GoogleAgendas.FirstOrDefaultAsync();
        if (conta is not null)
        {
            conta.RefreshToken = null;
            conta.CalendarId = null;
            conta.CalendarNome = null;
            conta.GoogleEmail = null;
            conta.StatusConexao = "desconectado";
            conta.AtualizadoEm = DateTime.UtcNow;
            await _db.SaveChangesAsync();
        }
        TempData["Ok"] = "Google desconectado. Os compromissos deixam de ser espelhados (os já criados permanecem no seu calendário).";
        return RedirectToPage();
    }
}
