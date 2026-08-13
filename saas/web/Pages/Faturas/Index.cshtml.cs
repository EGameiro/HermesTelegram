using HermesSaaS.Web.Data;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages.Faturas;

public class IndexModel : PageModel
{
    private readonly AppDbContext _db;
    public IndexModel(AppDbContext db) => _db = db;

    public Assinatura? Assinatura { get; set; }
    public List<Pagamento> Pagamentos { get; set; } = new();

    public async Task OnGetAsync()
    {
        Assinatura = await _db.Assinaturas.Include(a => a.Plano)
            .OrderByDescending(a => a.CriadoEm).FirstOrDefaultAsync();
        Pagamentos = await _db.Pagamentos.OrderByDescending(p => p.Data).ToListAsync();
    }
}
