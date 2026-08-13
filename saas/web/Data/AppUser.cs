using Microsoft.AspNetCore.Identity;

namespace HermesSaaS.Web.Data;

/// <summary>Usuário de autenticação (AspNetUsers). Cada AppUser aponta para um tenant
/// (Usuario/H01Usuarios) via UsuarioId — link lógico, sem FK cross-schema.</summary>
public class AppUser : IdentityUser
{
    public long UsuarioId { get; set; }
    public string NomeCompleto { get; set; } = string.Empty;
}
