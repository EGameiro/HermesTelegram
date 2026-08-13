using System.Security.Claims;
using HermesSaaS.Web.Data;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages.Conta;

public class IndexModel : PageModel
{
    private readonly AppDbContext _db;
    private readonly UserManager<AppUser> _users;
    private readonly SignInManager<AppUser> _signIn;

    public IndexModel(AppDbContext db, UserManager<AppUser> users, SignInManager<AppUser> signIn)
    {
        _db = db;
        _users = users;
        _signIn = signIn;
    }

    public Usuario? Usuario { get; set; }
    public Assinatura? Assinatura { get; set; }

    [BindProperty] public string? SenhaAtual { get; set; }
    [BindProperty] public string? SenhaNova { get; set; }
    [BindProperty] public string? ConfirmarExclusao { get; set; }

    private long Uid => long.Parse(User.FindFirstValue("UsuarioId") ?? "0");

    public async Task OnGetAsync()
    {
        Usuario = await _db.Usuarios.FirstOrDefaultAsync(u => u.Id == Uid);
        Assinatura = await _db.Assinaturas.Include(a => a.Plano)
            .OrderByDescending(a => a.CriadoEm).FirstOrDefaultAsync();
    }

    public async Task<IActionResult> OnPostSenhaAsync()
    {
        if (string.IsNullOrEmpty(SenhaAtual) || string.IsNullOrEmpty(SenhaNova))
        {
            TempData["Erro"] = "Preencha a senha atual e a nova.";
            return RedirectToPage();
        }
        var user = await _users.GetUserAsync(User);
        if (user is null) return RedirectToPage("/Login");

        var res = await _users.ChangePasswordAsync(user, SenhaAtual, SenhaNova);
        if (res.Succeeded)
        {
            await _signIn.RefreshSignInAsync(user);
            TempData["Ok"] = "Senha alterada. ✅";
        }
        else
        {
            TempData["Erro"] = string.Join(" ", res.Errors.Select(e => e.Description));
        }
        return RedirectToPage();
    }

    public async Task<IActionResult> OnPostCancelarAsync()
    {
        var assinatura = await _db.Assinaturas.OrderByDescending(a => a.CriadoEm).FirstOrDefaultAsync();
        if (assinatura != null) assinatura.Status = "cancelado";

        var usuario = await _db.Usuarios.FirstOrDefaultAsync(u => u.Id == Uid);
        if (usuario != null) { usuario.Status = "cancelado"; usuario.AtualizadoEm = DateTime.UtcNow; }

        await _db.SaveChangesAsync();
        TempData["Ok"] = "Assinatura cancelada. O assistente deixará de responder no Telegram.";
        return RedirectToPage();
    }

    public async Task<IActionResult> OnPostExcluirAsync()
    {
        var user = await _users.GetUserAsync(User);
        if (user is null) return RedirectToPage("/Login");

        if (string.IsNullOrEmpty(ConfirmarExclusao) || !await _users.CheckPasswordAsync(user, ConfirmarExclusao))
        {
            TempData["Erro"] = "Senha incorreta — nada foi excluído.";
            return RedirectToPage();
        }

        // Remove o login (AspNetUsers) e o tenant (H01Usuarios). O ON DELETE CASCADE do
        // schema apaga vínculos, assinaturas, config, contas, compromissos, uso e pagamentos.
        await _users.DeleteAsync(user);
        var usuario = await _db.Usuarios.FirstOrDefaultAsync(u => u.Id == Uid);
        if (usuario != null)
        {
            _db.Usuarios.Remove(usuario);
            await _db.SaveChangesAsync();
        }

        await _signIn.SignOutAsync();
        return RedirectToPage("/Login");
    }
}
