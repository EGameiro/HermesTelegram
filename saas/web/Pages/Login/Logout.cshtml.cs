using HermesSaaS.Web.Data;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace HermesSaaS.Web.Pages.Login;

public class LogoutModel : PageModel
{
    private readonly SignInManager<AppUser> _signIn;

    public LogoutModel(SignInManager<AppUser> signIn) => _signIn = signIn;

    public IActionResult OnGet() => RedirectToPage("/Login/Index");

    public async Task<IActionResult> OnPostAsync()
    {
        await _signIn.SignOutAsync();
        return RedirectToPage("/Login/Index");
    }
}
