using MailKit.Net.Smtp;
using MailKit.Security;
using MimeKit;

namespace HermesSaaS.Web.Services;

public interface IEmailService
{
    Task EnviarAsync(string destinatario, string assunto, string corpoHtml);
}

/// <summary>Envio de e-mail via SMTP (MailKit). Config em EmailSettings do appsettings.
/// Se o Host estiver vazio, apenas loga (não quebra o fluxo em dev sem SMTP).</summary>
public class EmailService : IEmailService
{
    private readonly IConfiguration _config;
    private readonly ILogger<EmailService> _log;

    public EmailService(IConfiguration config, ILogger<EmailService> log)
    {
        _config = config;
        _log = log;
    }

    public async Task EnviarAsync(string destinatario, string assunto, string corpoHtml)
    {
        var s = _config.GetSection("EmailSettings");
        var host = s["Host"];
        if (string.IsNullOrWhiteSpace(host))
        {
            _log.LogWarning("SMTP não configurado (EmailSettings:Host vazio). E-mail para {Dest} não enviado.", destinatario);
            return;
        }

        var msg = new MimeMessage();
        var nomeRem = s["NomeRemetente"] ?? "Hermes";
        var remetente = (s["EmailRemetente"] ?? "").Trim();
        var usuario = (s["Username"] ?? "").Trim();
        if (string.IsNullOrWhiteSpace(remetente))
            remetente = usuario;
        try
        {
            msg.From.Add(new MailboxAddress(nomeRem, remetente));
        }
        catch (ParseException)
        {
            // EmailRemetente malformado (ex.: caractere inválido) → cai pro Username.
            _log.LogWarning("EmailRemetente '{Rem}' inválido; usando Username '{User}' como remetente.", remetente, usuario);
            msg.From.Add(new MailboxAddress(nomeRem, usuario));
        }
        msg.To.Add(MailboxAddress.Parse(destinatario));
        msg.Subject = assunto;
        msg.Body = new TextPart("html") { Text = corpoHtml };

        var port = int.Parse(s["Port"] ?? "587");
        var useSsl = bool.Parse(s["UseSsl"] ?? "false");
        var socket = useSsl || port == 465 ? SecureSocketOptions.SslOnConnect : SecureSocketOptions.StartTls;

        _log.LogInformation("Enviando e-mail para {Dest} via {Host}:{Port} ({Socket}), remetente {From}, user {User}.",
            destinatario, host, port, socket, s["EmailRemetente"], s["Username"]);

        using var client = new SmtpClient();
        client.ServerCertificateValidationCallback = (_, _, _, _) => true;
        await client.ConnectAsync(host, port, socket);
        await client.AuthenticateAsync(s["Username"] ?? "", s["Password"] ?? "");
        await client.SendAsync(msg);
        await client.DisconnectAsync(true);
        _log.LogInformation("E-mail enviado com sucesso para {Dest}.", destinatario);
    }
}
