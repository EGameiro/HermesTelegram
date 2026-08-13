using System.ComponentModel.DataAnnotations;
using HermesSaaS.Web.Data;
using HermesSaaS.Web.Services;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace HermesSaaS.Web.Pages.Login;

public class EsqueciSenhaModel : PageModel
{
    private readonly UserManager<AppUser> _users;
    private readonly IEmailService _email;

    public EsqueciSenhaModel(UserManager<AppUser> users, IEmailService email)
    {
        _users = users;
        _email = email;
    }

    [BindProperty, Required, EmailAddress] public string Email { get; set; } = string.Empty;
    public bool Enviado { get; set; }

    public void OnGet() { }

    public async Task<IActionResult> OnPostAsync()
    {
        if (!ModelState.IsValid) return Page();

        var user = await _users.FindByEmailAsync(Email.Trim().ToLowerInvariant());
        // Só envia se existir — mas a mensagem é sempre a mesma (evita enumerar e-mails).
        if (user != null)
        {
            var token = await _users.GeneratePasswordResetTokenAsync(user);
            var link = Url.Page("/Login/RedefinirSenha", pageHandler: null,
                values: new { email = user.Email, token }, protocol: Request.Scheme);

            var corpo = $@"
                <p>Você pediu para redefinir sua senha do Hermes.</p>
                <p><a href=""{link}"">Clique aqui para criar uma nova senha</a>.</p>
                <p>Se não foi você, ignore este e-mail.</p>";
            try { await _email.EnviarAsync(user.Email!, "Redefinir senha — Hermes", corpo); }
            catch { /* não revela falha de envio ao usuário */ }
        }

        Enviado = true;
        return Page();
    }
}
