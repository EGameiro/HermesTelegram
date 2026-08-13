namespace HermesSaaS.Web.Services;

/// <summary>Hora local no fuso America/Sao_Paulo (mesmo do bot) — usado p/ casar o mês
/// da medição de uso. Cai para UTC se o fuso não existir no host.</summary>
public static class BrTime
{
    private static readonly TimeZoneInfo Tz = Resolve();

    private static TimeZoneInfo Resolve()
    {
        foreach (var id in new[] { "America/Sao_Paulo", "E. South America Standard Time" })
        {
            try { return TimeZoneInfo.FindSystemTimeZoneById(id); }
            catch { /* tenta o próximo */ }
        }
        return TimeZoneInfo.Utc;
    }

    public static DateTime Now => TimeZoneInfo.ConvertTimeFromUtc(DateTime.UtcNow, Tz);
}
