using System.Security.Claims;
using HermesSaaS.Web.Data;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages.Compromissos;

public class IndexModel : PageModel
{
    private readonly AppDbContext _db;
    public IndexModel(AppDbContext db) => _db = db;

    public List<Compromisso> Itens { get; set; } = new();

    [BindProperty] public InputModel Input { get; set; } = new();

    public class InputModel
    {
        public string Descricao { get; set; } = string.Empty;
        public DateTime? Quando { get; set; }
    }

    private long Uid => long.Parse(User.FindFirstValue("UsuarioId") ?? "0");

    public async Task OnGetAsync()
    {
        Itens = await _db.Compromissos
            .Where(c => !c.Avisado)
            .OrderBy(c => c.Quando)
            .ToListAsync();
    }

    public async Task<IActionResult> OnPostAddAsync()
    {
        if (string.IsNullOrWhiteSpace(Input.Descricao) || Input.Quando is null)
        {
            TempData["Erro"] = "Informe a descrição e a data/hora.";
            return RedirectToPage();
        }
        if (Input.Quando <= DateTime.Now)
        {
            TempData["Erro"] = "A data/hora precisa ser no futuro.";
            return RedirectToPage();
        }

        _db.Compromissos.Add(new Compromisso
        {
            UsuarioId = Uid,
            Descricao = Input.Descricao.Trim(),
            Quando = Input.Quando.Value,
            CriadoEm = DateTime.UtcNow,
        });
        await _db.SaveChangesAsync();
        TempData["Ok"] = "Compromisso agendado. Te aviso um pouco antes. 🔔";
        return RedirectToPage();
    }

    public async Task<IActionResult> OnPostRemoverAsync(long id)
    {
        var c = await _db.Compromissos.FirstOrDefaultAsync(x => x.Id == id);
        if (c != null) { _db.Compromissos.Remove(c); await _db.SaveChangesAsync(); TempData["Ok"] = "Compromisso cancelado."; }
        return RedirectToPage();
    }
}
