using System.Security.Claims;
using HermesSaaS.Web.Data;
using HermesSaaS.Web.Services;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages;

public class DashboardModel : PageModel
{
    private readonly AppDbContext _db;
    public DashboardModel(AppDbContext db) => _db = db;

    public Assinatura? Assinatura { get; set; }
    public Plano? Plano { get; set; }
    public TelegramVinculo? Vinculo { get; set; }
    public UsoMensal? Uso { get; set; }

    public bool Conectado => Vinculo?.StatusConexao == "conectado";
    public int VozUsadaSeg => Uso?.SegundosVoz ?? 0;
    public int? VozLimiteSeg => Plano?.LimiteVozSegMes;
    public long Mensagens => Uso?.QtdMensagens ?? 0;
    public long Tokens => Uso?.TokensLlm ?? 0;

    public async Task OnGetAsync()
    {
        var uid = long.Parse(User.FindFirstValue("UsuarioId") ?? "0");

        Assinatura = await _db.Assinaturas.Include(a => a.Plano)
            .OrderByDescending(a => a.CriadoEm).FirstOrDefaultAsync();
        Plano = Assinatura?.Plano;
        Vinculo = await _db.TelegramVinculos.FirstOrDefaultAsync();

        var agora = BrTime.Now;
        Uso = await _db.UsoMensal.FirstOrDefaultAsync(u => u.Ano == agora.Year && u.Mes == agora.Month);
    }
}
