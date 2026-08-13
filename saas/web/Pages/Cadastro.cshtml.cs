using System.ComponentModel.DataAnnotations;
using HermesSaaS.Web.Data;
using HermesSaaS.Web.Services;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace HermesSaaS.Web.Pages;

public class CadastroModel : PageModel
{
    private readonly OnboardingService _onboarding;
    private readonly SignInManager<AppUser> _signIn;
    private readonly UserManager<AppUser> _users;

    public CadastroModel(OnboardingService onboarding, SignInManager<AppUser> signIn, UserManager<AppUser> users)
    {
        _onboarding = onboarding;
        _signIn = signIn;
        _users = users;
    }

    [BindProperty] public InputModel Input { get; set; } = new();
    public List<string> Erros { get; set; } = new();

    public class InputModel
    {
        [Required] public string Nome { get; set; } = string.Empty;
        [Required, EmailAddress] public string Email { get; set; } = string.Empty;
        [Required, MinLength(6)] public string Senha { get; set; } = string.Empty;
        public bool AceiteTermos { get; set; }
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
            Erros.Add("Preencha todos os campos corretamente.");
            return Page();
        }
        if (!Input.AceiteTermos)
        {
            Erros.Add("É preciso aceitar os termos para continuar.");
            return Page();
        }

        var res = await _onboarding.RegistrarAsync(Input.Nome, Input.Email, Input.Senha, Input.AceiteTermos);
        if (!res.Sucesso)
        {
            Erros.AddRange(res.Erros);
            return Page();
        }

        var user = await _users.FindByEmailAsync(Input.Email.Trim().ToLowerInvariant());
        if (user != null)
            await _signIn.SignInAsync(user, isPersistent: true);

        return RedirectToPage("/Telegram/Conectar");
    }
}
