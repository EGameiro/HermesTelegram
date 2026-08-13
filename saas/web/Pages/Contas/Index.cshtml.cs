using System.Globalization;
using System.Security.Claims;
using HermesSaaS.Web.Data;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages.Contas;

public class IndexModel : PageModel
{
    private readonly AppDbContext _db;
    public IndexModel(AppDbContext db) => _db = db;

    public List<ContaPagar> Contas { get; set; } = new();
    public decimal TotalPendente { get; set; }

    [BindProperty] public InputModel Input { get; set; } = new();

    public class InputModel
    {
        public string Descricao { get; set; } = string.Empty;
        public string? Valor { get; set; }
        public DateOnly? Vencimento { get; set; }
    }

    private long Uid => long.Parse(User.FindFirstValue("UsuarioId") ?? "0");

    public async Task OnGetAsync()
    {
        Contas = await _db.ContasPagar
            .OrderBy(c => c.Pago).ThenBy(c => c.Vencimento)
            .ToListAsync();
        TotalPendente = Contas.Where(c => !c.Pago).Sum(c => c.Valor ?? 0);
    }

    public async Task<IActionResult> OnPostAddAsync()
    {
        if (string.IsNullOrWhiteSpace(Input.Descricao) || Input.Vencimento is null)
        {
            TempData["Erro"] = "Informe ao menos a descrição e o vencimento.";
            return RedirectToPage();
        }

        _db.ContasPagar.Add(new ContaPagar
        {
            UsuarioId = Uid,
            Descricao = Input.Descricao.Trim(),
            Valor = ParseValor(Input.Valor),
            Vencimento = Input.Vencimento.Value,
            CriadoEm = DateTime.UtcNow,
        });
        await _db.SaveChangesAsync();
        TempData["Ok"] = "Conta adicionada. O bot vai te lembrar no vencimento. 🔔";
        return RedirectToPage();
    }

    public async Task<IActionResult> OnPostPagarAsync(long id)
    {
        var c = await _db.ContasPagar.FirstOrDefaultAsync(x => x.Id == id);
        if (c != null) { c.Pago = true; await _db.SaveChangesAsync(); TempData["Ok"] = "Conta marcada como paga."; }
        return RedirectToPage();
    }

    public async Task<IActionResult> OnPostRemoverAsync(long id)
    {
        var c = await _db.ContasPagar.FirstOrDefaultAsync(x => x.Id == id);
        if (c != null) { _db.ContasPagar.Remove(c); await _db.SaveChangesAsync(); TempData["Ok"] = "Conta removida."; }
        return RedirectToPage();
    }

    private static decimal? ParseValor(string? s)
    {
        if (string.IsNullOrWhiteSpace(s)) return null;
        s = s.Trim().Replace("R$", "").Trim();
        // aceita "100,50" (pt-BR) ou "100.50" (invariante)
        if (decimal.TryParse(s, NumberStyles.Any, new CultureInfo("pt-BR"), out var v)) return v;
        if (decimal.TryParse(s, NumberStyles.Any, CultureInfo.InvariantCulture, out v)) return v;
        return null;
    }
}
