using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;
using Microsoft.Extensions.Configuration;

namespace HermesSaaS.Web.Data;

/// <summary>Usada por `dotnet ef migrations` em design-time. Lê a connection string do
/// appsettings (e appsettings.Development.json) e detecta a versão real do MySQL, para que
/// a migration seja gerada com o tamanho de chave correto para o servidor de destino.</summary>
public class AppDbContextFactory : IDesignTimeDbContextFactory<AppDbContext>
{
    public AppDbContext CreateDbContext(string[] args)
    {
        var config = new ConfigurationBuilder()
            .SetBasePath(Directory.GetCurrentDirectory())
            .AddJsonFile("appsettings.json", optional: true)
            .AddJsonFile("appsettings.Development.json", optional: true)
            .AddEnvironmentVariables()
            .Build();

        var conn = config.GetConnectionString("DefaultConnection")
            ?? "Server=localhost;Port=3306;Database=hermes_saas;User=root;Password=;";

        var options = new DbContextOptionsBuilder<AppDbContext>()
            .UseMySql(conn, ServerVersion.AutoDetect(conn))
            .Options;
        return new AppDbContext(options, new HttpContextAccessor());
    }
}
