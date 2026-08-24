using System.Text.Json;

namespace HermesSaaS.Web.Services;

public record GoogleTokens(string AccessToken, string? RefreshToken, string? Email);
public record GoogleCalendar(string Id, string Nome, bool Primary);

/// <summary>Cliente OAuth + Calendar API do Google (lado painel): monta a URL de
/// consentimento, troca o code por tokens, lê o e-mail da conta e lista as agendas.
/// O bot (Python) é quem cria os eventos; aqui só cuidamos da conexão/escolha da agenda.</summary>
public class GoogleService
{
    // Escopos: criar/editar eventos + listar as agendas (p/ o usuário escolher) + e-mail.
    private const string SCOPES =
        "https://www.googleapis.com/auth/calendar.events " +
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly " +
        "openid email";

    private const string AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
    private const string TOKEN_URL = "https://oauth2.googleapis.com/token";
    private const string USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo";
    private const string CALLIST_URL = "https://www.googleapis.com/calendar/v3/users/me/calendarList";

    private readonly IHttpClientFactory _http;
    private readonly IConfiguration _cfg;

    public GoogleService(IHttpClientFactory http, IConfiguration cfg)
    {
        _http = http;
        _cfg = cfg;
    }

    public string ClientId => _cfg["Google:ClientId"] ?? "";
    public string ClientSecret => _cfg["Google:ClientSecret"] ?? "";
    public bool Configurado => !string.IsNullOrEmpty(ClientId) && !string.IsNullOrEmpty(ClientSecret);

    /// <summary>URL de consentimento do Google. `access_type=offline` + `prompt=consent`
    /// garantem que vem um refresh token (mesmo em reconexões).</summary>
    public string BuildAuthUrl(string redirectUri, string state)
    {
        var q = new Dictionary<string, string>
        {
            ["client_id"] = ClientId,
            ["redirect_uri"] = redirectUri,
            ["response_type"] = "code",
            ["scope"] = SCOPES,
            ["access_type"] = "offline",
            ["prompt"] = "consent",
            ["include_granted_scopes"] = "true",
            ["state"] = state,
        };
        var qs = string.Join("&", q.Select(kv => $"{Uri.EscapeDataString(kv.Key)}={Uri.EscapeDataString(kv.Value)}"));
        return $"{AUTH_URL}?{qs}";
    }

    /// <summary>Troca o `code` do callback por tokens e busca o e-mail da conta.</summary>
    public async Task<GoogleTokens?> ExchangeCodeAsync(string code, string redirectUri)
    {
        var client = _http.CreateClient();
        var resp = await client.PostAsync(TOKEN_URL, new FormUrlEncodedContent(new Dictionary<string, string>
        {
            ["code"] = code,
            ["client_id"] = ClientId,
            ["client_secret"] = ClientSecret,
            ["redirect_uri"] = redirectUri,
            ["grant_type"] = "authorization_code",
        }));
        if (!resp.IsSuccessStatusCode)
            return null;

        using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
        var root = doc.RootElement;
        var access = root.TryGetProperty("access_token", out var a) ? a.GetString() : null;
        if (string.IsNullOrEmpty(access))
            return null;
        var refresh = root.TryGetProperty("refresh_token", out var r) ? r.GetString() : null;
        var email = await GetEmailAsync(access);
        return new GoogleTokens(access, refresh, email);
    }

    /// <summary>Renova o access token a partir do refresh token guardado.</summary>
    public async Task<string?> AccessTokenFromRefreshAsync(string refreshToken)
    {
        var client = _http.CreateClient();
        var resp = await client.PostAsync(TOKEN_URL, new FormUrlEncodedContent(new Dictionary<string, string>
        {
            ["client_id"] = ClientId,
            ["client_secret"] = ClientSecret,
            ["refresh_token"] = refreshToken,
            ["grant_type"] = "refresh_token",
        }));
        if (!resp.IsSuccessStatusCode)
            return null;
        using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
        return doc.RootElement.TryGetProperty("access_token", out var a) ? a.GetString() : null;
    }

    private async Task<string?> GetEmailAsync(string accessToken)
    {
        try
        {
            var client = _http.CreateClient();
            var req = new HttpRequestMessage(HttpMethod.Get, USERINFO_URL);
            req.Headers.Authorization = new("Bearer", accessToken);
            var resp = await client.SendAsync(req);
            if (!resp.IsSuccessStatusCode) return null;
            using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
            return doc.RootElement.TryGetProperty("email", out var e) ? e.GetString() : null;
        }
        catch { return null; }
    }

    /// <summary>Lista as agendas da conta (p/ o usuário escolher qual o Hermes alimenta).</summary>
    public async Task<List<GoogleCalendar>> ListCalendarsAsync(string accessToken)
    {
        var lista = new List<GoogleCalendar>();
        try
        {
            var client = _http.CreateClient();
            var req = new HttpRequestMessage(HttpMethod.Get, CALLIST_URL + "?minAccessRole=writer&maxResults=250");
            req.Headers.Authorization = new("Bearer", accessToken);
            var resp = await client.SendAsync(req);
            if (!resp.IsSuccessStatusCode) return lista;
            using var doc = JsonDocument.Parse(await resp.Content.ReadAsStringAsync());
            if (!doc.RootElement.TryGetProperty("items", out var items)) return lista;
            foreach (var it in items.EnumerateArray())
            {
                var id = it.TryGetProperty("id", out var i) ? i.GetString() : null;
                if (string.IsNullOrEmpty(id)) continue;
                var nome = it.TryGetProperty("summary", out var s) ? s.GetString() ?? id : id;
                var primary = it.TryGetProperty("primary", out var p) && p.GetBoolean();
                lista.Add(new GoogleCalendar(id, nome, primary));
            }
        }
        catch { /* devolve o que tiver */ }
        // Agenda principal primeiro.
        return lista.OrderByDescending(c => c.Primary).ThenBy(c => c.Nome).ToList();
    }
}
