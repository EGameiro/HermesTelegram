using HermesSaaS.Web.Data;
using HermesSaaS.Web.Services;
using Microsoft.AspNetCore.Authorization;
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
builder.Services.AddDbContext<AppDbContext>(o =>
    o.UseMySql(conn, ServerVersion.AutoDetect(conn)));

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

var app = builder.Build();

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error");
    app.UseHsts();
}

app.UseHttpsRedirection();
app.UseStaticFiles();
app.UseRouting();
app.UseAuthentication();
app.UseAuthorization();
app.MapRazorPages();

await DatabaseSeeder.SeedAsync(app.Services, app.Configuration);

app.Run();
