using System.Security.Claims;
using HermesSaaS.Web.Data;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Pages.Conta;

public class ConfiguracoesModel : PageModel
{
    private readonly AppDbContext _db;
    public ConfiguracoesModel(AppDbContext db) => _db = db;

    [BindProperty] public InputModel Input { get; set; } = new();
    public bool Salvo { get; set; }

    public class InputModel
    {
        public string Cidade { get; set; } = "Jacareí";
        public bool VozAtiva { get; set; } = true;
        public byte HoraLembrete { get; set; } = 8;
        public int AntecedenciaMin { get; set; } = 15;
        public string Fuso { get; set; } = "America/Sao_Paulo";
    }

    private long Uid => long.Parse(User.FindFirstValue("UsuarioId") ?? "0");

    public async Task<IActionResult> OnGetAsync()
    {
        var cfg = await _db.Configuracoes.FirstOrDefaultAsync();
        if (cfg != null)
        {
            Input = new InputModel
            {
                Cidade = cfg.Cidade,
                VozAtiva = cfg.VozAtiva,
                HoraLembrete = cfg.HoraLembrete,
                AntecedenciaMin = cfg.AntecedenciaMin,
                Fuso = cfg.Fuso,
            };
        }
        return Page();
    }

    public async Task<IActionResult> OnPostAsync()
    {
        var cfg = await _db.Configuracoes.FirstOrDefaultAsync();
        if (cfg == null)
        {
            cfg = new Configuracao { UsuarioId = Uid };
            _db.Configuracoes.Add(cfg);
        }
        cfg.Cidade = string.IsNullOrWhiteSpace(Input.Cidade) ? "Jacareí" : Input.Cidade.Trim();
        cfg.VozAtiva = Input.VozAtiva;
        cfg.HoraLembrete = (byte)Math.Clamp((int)Input.HoraLembrete, 0, 23);
        cfg.AntecedenciaMin = Math.Clamp(Input.AntecedenciaMin, 0, 240);
        cfg.Fuso = string.IsNullOrWhiteSpace(Input.Fuso) ? "America/Sao_Paulo" : Input.Fuso.Trim();
        await _db.SaveChangesAsync();

        Salvo = true;
        return Page();
    }
}
