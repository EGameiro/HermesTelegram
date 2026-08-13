using HermesSaaS.Web.Data;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages.Admin;

[Authorize(Roles = "Admin")]
public class ClientesModel : PageModel
{
    private readonly AppDbContext _db;
    public ClientesModel(AppDbContext db) => _db = db;

    public List<ClienteVm> Clientes { get; set; } = new();
    public List<Plano> Planos { get; set; } = new();
    [TempData] public string? Msg { get; set; }

    public record ClienteVm(
        long UsuarioId, string Nome, string Email, string StatusUsuario,
        string? PlanoNome, string? StatusAssinatura, DateOnly? TrialAte,
        bool Conectado, DateTime CriadoEm);

    public async Task OnGetAsync()
    {
        Planos = await _db.Planos.AsNoTracking().Where(p => p.Ativo).OrderBy(p => p.PrecoMensal).ToListAsync();

        // Admin vê TODOS os tenants -> ignora os HasQueryFilter (que escopam por UsuarioId).
        var usuarios = await _db.Usuarios.AsNoTracking().OrderByDescending(u => u.CriadoEm).ToListAsync();
        var assinaturas = await _db.Assinaturas.IgnoreQueryFilters().Include(a => a.Plano).AsNoTracking().ToListAsync();
        var vinculos = await _db.TelegramVinculos.IgnoreQueryFilters().AsNoTracking().ToListAsync();

        foreach (var u in usuarios)
        {
            var a = assinaturas.Where(x => x.UsuarioId == u.Id).OrderByDescending(x => x.CriadoEm).FirstOrDefault();
            var v = vinculos.FirstOrDefault(x => x.UsuarioId == u.Id);
            Clientes.Add(new ClienteVm(
                u.Id, u.NomeCompleto, u.Email, u.Status,
                a?.Plano?.Nome, a?.Status, a?.TrialAte,
                v?.StatusConexao == "conectado", u.CriadoEm));
        }
    }

    public async Task<IActionResult> OnPostAtivarAsync(long usuarioId, int planoId)
    {
        var usuario = await _db.Usuarios.FirstOrDefaultAsync(u => u.Id == usuarioId);
        var plano = await _db.Planos.FirstOrDefaultAsync(p => p.Id == planoId);
        if (usuario is null || plano is null)
        {
            Msg = "Cliente ou plano não encontrado.";
            return RedirectToPage();
        }

        var assinatura = await _db.Assinaturas.IgnoreQueryFilters()
            .Where(a => a.UsuarioId == usuarioId)
            .OrderByDescending(a => a.CriadoEm).FirstOrDefaultAsync();

        var hoje = DateOnly.FromDateTime(DateTime.UtcNow);
        if (assinatura is null)
        {
            assinatura = new Assinatura { UsuarioId = usuarioId, CriadoEm = DateTime.UtcNow, DataInicio = hoje };
            _db.Assinaturas.Add(assinatura);
        }
        assinatura.PlanoId = plano.Id;
        assinatura.Status = "ativo";
        assinatura.AtivacaoManual = true;
        assinatura.DataInicio = hoje;
        assinatura.DataRenovacao = hoje.AddMonths(1);

        usuario.Status = "ativo";
        usuario.AtualizadoEm = DateTime.UtcNow;

        await _db.SaveChangesAsync();
        Msg = $"Plano {plano.Nome} ativado para {usuario.NomeCompleto}.";
        return RedirectToPage();
    }
}
