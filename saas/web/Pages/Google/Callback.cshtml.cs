using System.Security.Claims;
using HermesSaaS.Web.Data;
using HermesSaaS.Web.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages.Google;

public class CallbackModel : PageModel
{
    private readonly AppDbContext _db;
    private readonly GoogleService _google;

    public CallbackModel(AppDbContext db, GoogleService google)
    {
        _db = db;
        _google = google;
    }

    private long Uid => long.Parse(User.FindFirstValue("UsuarioId") ?? "0");
    private string RedirectUri => $"{Request.Scheme}://{Request.Host}/Google/Callback";

    public async Task<IActionResult> OnGetAsync(string? code, string? state, string? error)
    {
        if (!string.IsNullOrEmpty(error))
        {
            TempData["Erro"] = "Conexão com o Google cancelada.";
            return RedirectToPage("/Google/Conectar");
        }

        var esperado = TempData["gstate"] as string;
        if (string.IsNullOrEmpty(code) || string.IsNullOrEmpty(state) || state != esperado)
        {
            TempData["Erro"] = "Não foi possível validar a conexão. Tente novamente.";
            return RedirectToPage("/Google/Conectar");
        }

        var tokens = await _google.ExchangeCodeAsync(code, RedirectUri);
        if (tokens is null || string.IsNullOrEmpty(tokens.RefreshToken))
        {
            // Sem refresh token: normalmente é reconexão sem "prompt=consent" ou erro de troca.
            TempData["Erro"] = "O Google não devolveu a autorização completa. Tente conectar de novo.";
            return RedirectToPage("/Google/Conectar");
        }

        var conta = await _db.GoogleAgendas.FirstOrDefaultAsync();
        if (conta is null)
        {
            conta = new GoogleAgenda { UsuarioId = Uid };
            _db.GoogleAgendas.Add(conta);
        }
        conta.RefreshToken = tokens.RefreshToken;
        conta.GoogleEmail = tokens.Email;
        conta.StatusConexao = "conectado";
        conta.ConectadoEm = DateTime.UtcNow;
        conta.AtualizadoEm = DateTime.UtcNow;
        // 1ª conexão: assume a agenda principal; o usuário pode trocar na tela seguinte.
        if (string.IsNullOrEmpty(conta.CalendarId))
        {
            conta.CalendarId = "primary";
            conta.CalendarNome = "Agenda principal";
        }
        await _db.SaveChangesAsync();

        TempData["Ok"] = "Google conectado! Agora escolha em qual agenda o Hermes vai lançar os compromissos.";
        return RedirectToPage("/Google/Conectar");
    }
}
