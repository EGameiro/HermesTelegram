using Microsoft.AspNetCore.Identity;
using Microsoft.Extensions.Options;
using System.Security.Claims;

namespace HermesSaaS.Web.Data;

/// <summary>Injeta UsuarioId (tenant) e NomeCompleto nos claims do cookie após o login —
/// o AppDbContext usa o claim UsuarioId para escopar todas as queries multi-tenant.</summary>
public class CustomClaimsFactory : UserClaimsPrincipalFactory<AppUser, IdentityRole>
{
    public CustomClaimsFactory(
        UserManager<AppUser> userManager,
        RoleManager<IdentityRole> roleManager,
        IOptions<IdentityOptions> options)
        : base(userManager, roleManager, options)
    {
    }

    protected override async Task<ClaimsIdentity> GenerateClaimsAsync(AppUser user)
    {
        var identity = await base.GenerateClaimsAsync(user);
        identity.AddClaim(new Claim("UsuarioId", user.UsuarioId.ToString()));
        identity.AddClaim(new Claim("NomeCompleto", user.NomeCompleto ?? string.Empty));
        return identity;
    }
}
