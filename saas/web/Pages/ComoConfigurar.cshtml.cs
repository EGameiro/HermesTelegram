using Microsoft.AspNetCore.Mvc.RazorPages;

namespace HermesSaaS.Web.Pages;

public class ComoConfigurarModel : PageModel
{
    private readonly IConfiguration _config;

    public ComoConfigurarModel(IConfiguration config) => _config = config;

    /// <summary>Número do bot de WhatsApp (só dígitos, E.164). Vazio = não configurado.</summary>
    public string BotNumero => _config["WhatsApp:BotNumber"] ?? "";

    public void OnGet() { }
}
