using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

namespace HermesSaaS.Web.Data;

/// <summary>Roda no startup: aplica a migration do Identity (só tabelas AspNet*),
/// garante as roles e cria o usuário admin do SaaS (dono).</summary>
public static class DatabaseSeeder
{
    public static readonly string[] Roles = { "Admin", "Cliente" };

    public static async Task SeedAsync(IServiceProvider services, IConfiguration config)
    {
        using var scope = services.CreateScope();
        var sp = scope.ServiceProvider;
        var db = sp.GetRequiredService<AppDbContext>();
        var roleMgr = sp.GetRequiredService<RoleManager<IdentityRole>>();
        var userMgr = sp.GetRequiredService<UserManager<AppUser>>();

        // Cria/atualiza só as tabelas AspNet* (H01* são ExcludeFromMigrations).
        await db.Database.MigrateAsync();

        foreach (var r in Roles)
            if (!await roleMgr.RoleExistsAsync(r))
                await roleMgr.CreateAsync(new IdentityRole(r));

        var email = (config["AdminSeed:Email"] ?? "admin@hermes.local").Trim().ToLowerInvariant();
        var senha = config["AdminSeed:Senha"] ?? "Admin@123";
        var nome = config["AdminSeed:Nome"] ?? "Administrador Hermes";

        if (await userMgr.FindByEmailAsync(email) is null)
        {
            // Todo AppUser precisa de um tenant (Usuario). O admin ganha um mínimo.
            var usuario = await db.Usuarios.FirstOrDefaultAsync(u => u.Email == email);
            if (usuario is null)
            {
                usuario = new Usuario { NomeCompleto = nome, Email = email, Status = "ativo", CriadoEm = DateTime.UtcNow };
                db.Usuarios.Add(usuario);
                await db.SaveChangesAsync();
                db.Configuracoes.Add(new Configuracao { UsuarioId = usuario.Id });
                await db.SaveChangesAsync();
            }

            var admin = new AppUser
            {
                UserName = email,
                Email = email,
                NomeCompleto = nome,
                UsuarioId = usuario.Id,
                EmailConfirmed = true,
            };
            var res = await userMgr.CreateAsync(admin, senha);
            if (res.Succeeded)
                await userMgr.AddToRoleAsync(admin, "Admin");
        }
    }
}
