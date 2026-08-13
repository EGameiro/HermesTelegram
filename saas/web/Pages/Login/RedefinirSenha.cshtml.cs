using System.ComponentModel.DataAnnotations;
using HermesSaaS.Web.Data;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace HermesSaaS.Web.Pages.Login;

public class RedefinirSenhaModel : PageModel
{
    private readonly UserManager<AppUser> _users;
    public RedefinirSenhaModel(UserManager<AppUser> users) => _users = users;

    [BindProperty(SupportsGet = true)] public string Email { get; set; } = string.Empty;
    [BindProperty(SupportsGet = true)] public string Token { get; set; } = string.Empty;
    [BindProperty, Required, MinLength(6)] public string NovaSenha { get; set; } = string.Empty;

    public string? Erro { get; set; }
    public bool Sucesso { get; set; }

    public IActionResult OnGet()
    {
        if (string.IsNullOrEmpty(Email) || string.IsNullOrEmpty(Token))
        {
            Erro = "Link inválido ou incompleto. Solicite um novo.";
        }
        return Page();
    }

    public async Task<IActionResult> OnPostAsync()
    {
        if (!ModelState.IsValid)
        {
            Erro = "A nova senha precisa ter ao menos 6 caracteres.";
            return Page();
        }

        var user = await _users.FindByEmailAsync(Email.Trim().ToLowerInvariant());
        if (user is null)
        {
            Erro = "Link inválido. Solicite um novo.";
            return Page();
        }

        var res = await _users.ResetPasswordAsync(user, Token, NovaSenha);
        if (res.Succeeded)
        {
            Sucesso = true;
            return Page();
        }

        Erro = "Não foi possível redefinir (o link pode ter expirado). " +
               string.Join(" ", res.Errors.Select(e => e.Description));
        return Page();
    }
}
