using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace HermesSaaS.Web.Pages;

public class IndexModel : PageModel
{
    // Landing pública. Quem já está logado vai direto pro painel.
    public IActionResult OnGet()
    {
        if (User.Identity?.IsAuthenticated == true)
            return RedirectToPage("/Dashboard");
        return Page();
    }
}
