using HermesSaaS.Web.Data;
using HermesSaaS.Web.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.DataProtection;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddRazorPages(options =>
{
    // Todo o painel exige login; as páginas públicas liberam explicitamente com [AllowAnonymous].
    options.Conventions.AuthorizeFolder("/");
    options.Conventions.AllowAnonymousToFolder("/Login");
    options.Conventions.AllowAnonymousToPage("/Cadastro");
    options.Conventions.AllowAnonymousToPage("/AcessoNegado");
});

builder.Services.AddHttpContextAccessor();

var conn = builder.Configuration.GetConnectionString("DefaultConnection")
    ?? throw new InvalidOperationException("ConnectionString 'DefaultConnection' não configurada.");
// Versão fixa (MySQL 8 do SmartASP) — evita o AutoDetect abrir conexão no startup,
// que derruba o app se o banco demorar/negar no boot.
builder.Services.AddDbContext<AppDbContext>(o =>
    o.UseMySql(conn, new MySqlServerVersion(new Version(8, 0, 39))));

builder.Services.AddIdentity<AppUser, IdentityRole>(o =>
{
    o.Password.RequireDigit = true;
    o.Password.RequireLowercase = true;
    o.Password.RequireNonAlphanumeric = false;
    o.Password.RequireUppercase = false;
    o.Password.RequiredLength = 6;
    o.SignIn.RequireConfirmedAccount = false;
    o.User.RequireUniqueEmail = true;
})
.AddEntityFrameworkStores<AppDbContext>()
.AddDefaultTokenProviders();

builder.Services.AddScoped<IUserClaimsPrincipalFactory<AppUser>, CustomClaimsFactory>();

builder.Services.ConfigureApplicationCookie(o =>
{
    o.LoginPath = "/Login";
    o.LogoutPath = "/Login/Logout";
    o.AccessDeniedPath = "/AcessoNegado";
    o.ExpireTimeSpan = TimeSpan.FromHours(8);
    o.SlidingExpiration = true;
});

builder.Services.AddScoped<OnboardingService>();
builder.Services.AddScoped<IEmailService, EmailService>();

// Persiste as chaves de DataProtection em disco. No host shared (sem user profile/HKLM)
// elas ficariam só em memória → cookie de login e token antiforgery quebram a cada
// reciclagem do processo. A pasta 'dp-keys' fica no content root (o app tem escrita ali).
builder.Services.AddDataProtection()
    .PersistKeysToFileSystem(new DirectoryInfo(
        Path.Combine(builder.Environment.ContentRootPath, "dp-keys")))
    .SetApplicationName("HermesSaaS");

// Atrás do Traefik (VPS): confia no X-Forwarded-Proto/For pra saber que o cliente
// entrou por HTTPS. KnownProxies/Networks limpos porque o proxy está na rede Docker
// e seu IP não é fixo/conhecido.
builder.Services.Configure<ForwardedHeadersOptions>(o =>
{
    o.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    o.KnownNetworks.Clear();
    o.KnownProxies.Clear();
});

var app = builder.Build();

// PRIMEIRO middleware: aplica os headers do proxy antes de qualquer coisa ler o scheme.
app.UseForwardedHeaders();

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error");
    app.UseHsts();
}

// Sem UseHttpsRedirection: o Traefik já termina o TLS e repassa HTTP na 8080.
app.UseStaticFiles();
app.UseRouting();
app.UseAuthentication();
app.UseAuthorization();
app.MapRazorPages();

await DatabaseSeeder.SeedAsync(app.Services, app.Configuration);

app.Run();
