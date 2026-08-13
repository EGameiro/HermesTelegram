using System.ComponentModel.DataAnnotations;
using HermesSaaS.Web.Data;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace HermesSaaS.Web.Pages.Login;

public class IndexModel : PageModel
{
    private readonly SignInManager<AppUser> _signIn;

    public IndexModel(SignInManager<AppUser> signIn) => _signIn = signIn;

    [BindProperty] public InputModel Input { get; set; } = new();
    public string? Erro { get; set; }

    public class InputModel
    {
        [Required, EmailAddress] public string Email { get; set; } = string.Empty;
        [Required] public string Senha { get; set; } = string.Empty;
    }

    public IActionResult OnGet()
    {
        if (User.Identity?.IsAuthenticated == true)
            return RedirectToPage("/Dashboard");
        return Page();
    }

    public async Task<IActionResult> OnPostAsync()
    {
        if (!ModelState.IsValid)
        {
            Erro = "Preencha e-mail e senha.";
            return Page();
        }

        var res = await _signIn.PasswordSignInAsync(
            Input.Email.Trim(), Input.Senha, isPersistent: true, lockoutOnFailure: false);

        if (res.Succeeded)
            return RedirectToPage("/Dashboard");

        Erro = "E-mail ou senha inválidos.";
        return Page();
    }
}
