"""Apresentação de alertas; sem acesso a rede, estado ou transporte SMTP."""
import html
import ipaddress
import re
import urllib.parse

UNKNOWN = 'Não informado / precisa confirmar'


def text(value, fallback=UNKNOWN):
    if value is None or not str(value).strip():
        return fallback
    return str(value).strip()


def escape(value, fallback=UNKNOWN):
    return html.escape(text(value, fallback), quote=True)


def safe_url(value, official_domains):
    """Aceitar somente HTTPS em hosts oficiais permitidos, sem credenciais."""
    if not isinstance(value, str) or re.search(r'[\s\x00-\x1f\x7f\\<>"\']', value):
        return None
    try:
        parsed = urllib.parse.urlsplit(value)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme != 'https' or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)):
            return None
        # Não transformar endereços locais/IPs em links de candidatura.
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        if not any(host == domain or host.endswith('.' + domain)
                   for domain in official_domains):
            return None
        return value
    except ValueError:
        return None


def application_url(job, official_domains):
    if job.get('official') is not True:
        return None
    return (safe_url(job.get('application_url'), official_domains)
            or safe_url(job.get('url'), official_domains))


def render_plain(rows, fields, official_domains):
    """Versão textual completa compartilhada entre alertas e prévias isoladas."""
    chunks = []
    for _, _, job, updated in rows:
        values = {**job, 'url': safe_url(job.get('url'), official_domains)
                  if job.get('official') is True else None}
        chunks.append(('Vaga atualizada\n' if updated else 'Vaga nova\n')
                      + '\n'.join(f'{label}: {values.get(key) or UNKNOWN}'
                                  for key, label in fields.items())
                      + '\nLink para candidatura: '
                      + (application_url(job, official_domains) or UNKNOWN))
    return '\n\n\n\n' + '\n\n'.join(chunks)


def subject(rows):
    updated = sum(bool(row[3]) for row in rows)
    new = len(rows) - updated
    parts = []
    if new:
        parts.append(f'{new} vaga' + ('s novas' if new != 1 else ' nova'))
    if updated:
        parts.append(f'{updated} vaga' + ('s atualizadas' if updated != 1 else ' atualizada'))
    return 'Radar TI | ' + (' e '.join(parts) or 'Nenhuma novidade')


def summary(value, limit=260):
    value = re.sub(r'\s+', ' ', text(value))
    if len(value) <= limit:
        return value
    return value[:limit - 1].rsplit(' ', 1)[0].rstrip('.,;:') + '…'


def known(value):
    return bool(value and str(value).strip() and not str(value).lower().startswith('não informado'))


def render_html(rows, generated_at, official_domains):
    """Renderizar uma newsletter independente, com tabelas e estilos inline."""
    cards = []
    for _, _, job, updated in rows:
        label = 'VAGA ATUALIZADA' if updated else 'NOVA OPORTUNIDADE'
        badge_bg, badge_fg = ('#FFF3DF', '#805000') if updated else ('#EAF0FF', '#244AC4')
        optional = ''
        deadline = job.get('deadline') if known(job.get('deadline')) else job.get('deadline_iso')
        for value, title in [(job.get('salary'), 'Bolsa / salário'), (deadline, 'Inscrições até')]:
            if known(value):
                optional += f'<p style="margin:0 0 10px;font-size:14px;line-height:22px;color:#4C5A70;"><strong style="color:#101E38;">{title}:</strong> {escape(value)}</p>'
        url = application_url(job, official_domains)
        if url:
            cta = f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:22px;"><tr><td bgcolor="#315CE8" style="border-radius:6px;mso-padding-alt:14px 20px;"><a href="{escape(url)}" style="display:inline-block;padding:14px 20px;font-family:Arial,Helvetica,sans-serif;font-size:14px;font-weight:bold;line-height:20px;color:#FFFFFF;text-decoration:none;border-radius:6px;">Ver vaga e candidatar-se</a></td></tr></table>'''
        else:
            cta = '<p style="margin:22px 0 0;font-size:13px;line-height:20px;color:#4C5A70;">Link oficial indisponível para este alerta. Confirme a candidatura na página da empresa.</p>'
        cards.append(f'''<tr><td style="padding:0 0 18px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#FFFFFF" style="width:100%;border:1px solid #DFE5EE;border-radius:10px;"><tr><td class="card" style="padding:26px;overflow-wrap:anywhere;word-break:break-word;">
<span style="display:inline-block;background-color:{badge_bg};color:{badge_fg};padding:5px 9px;border-radius:4px;font-size:10px;line-height:16px;font-weight:bold;letter-spacing:1px;">{label}</span>
<h2 style="margin:16px 0 7px;font-size:22px;line-height:29px;font-weight:bold;color:#101E38;">{escape(job.get('title'))}</h2>
<p style="margin:0 0 6px;font-size:16px;line-height:24px;font-weight:bold;color:#34435C;">{escape(job.get('company'))}</p>
<p style="margin:0 0 16px;font-size:13px;line-height:21px;color:#66748A;">{escape(job.get('location'))} &middot; {escape(job.get('modality'))}</p>
<p style="margin:0 0 16px;font-size:12px;line-height:20px;color:#315CE8;font-weight:bold;">{escape(job.get('area'))}</p>
{optional}
<p style="margin:16px 0 8px;font-size:14px;line-height:23px;color:#4C5A70;">{escape(summary(job.get('activities')))}</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:16px;"><tr><td bgcolor="#F3F6FB" style="padding:14px 16px;border-left:3px solid #315CE8;border-radius:3px;">
<p style="margin:0 0 5px;font-size:11px;line-height:17px;letter-spacing:0.7px;font-weight:bold;color:#315CE8;">POR QUE COMBINA COM SEU PERFIL</p>
<p style="margin:0;font-size:13px;line-height:21px;color:#34435C;">{escape(job.get('compatibility'))}</p></td></tr></table>
{cta}</td></tr></table></td></tr>''')
    count = len(rows)
    count_label = 'oportunidade selecionada' if count == 1 else 'oportunidades selecionadas'
    return f'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light"><title>Radar TI | Monitor de Vagas</title>
<style>@media only screen and (max-width:620px){{.content{{padding-left:16px!important;padding-right:16px!important;}}.card{{padding:20px!important;}}.headline{{font-size:28px!important;line-height:34px!important;}}}}</style></head>
<body style="margin:0;padding:0;background-color:#EEF2F7;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%;">
<div style="display:none;font-size:1px;line-height:1px;color:#EEF2F7;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">{count} {count_label} para seu perfil de TI. Confira vagas novas e atualizações.</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#EEF2F7"><tr><td align="center" style="padding:24px 8px;">
<!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:600px;">
<tr><td class="content" bgcolor="#101E38" style="padding:32px;border-radius:12px 12px 0 0;">
<p style="margin:0 0 30px;font-size:20px;line-height:26px;font-weight:bold;color:#FFFFFF;">Radar TI <span style="font-weight:normal;font-size:12px;color:#B5C4DE;">| Monitor de Vagas</span></p>
<p style="margin:0 0 12px;font-size:10px;line-height:16px;letter-spacing:2px;font-weight:bold;color:#9DB5FF;">SEU PRÓXIMO PASSO EM TECNOLOGIA</p>
<h1 class="headline" style="margin:0 0 16px;font-size:32px;line-height:39px;letter-spacing:-0.5px;font-weight:bold;color:#FFFFFF;">Sua próxima oportunidade pode estar aqui.</h1>
<p style="margin:0 0 24px;font-size:14px;line-height:23px;color:#C5D0E3;">Vagas novas e atualizações alinhadas ao seu perfil, reunidas para facilitar seu próximo passo.</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr><td bgcolor="#213557" style="padding:10px 14px;border-radius:5px;color:#FFFFFF;font-size:13px;line-height:20px;"><strong>{count:02d}</strong> &nbsp; {count_label}</td></tr></table>
</td></tr>
<tr><td class="content" style="padding:26px 24px 8px;"><p style="margin:0 0 18px;font-size:11px;line-height:18px;letter-spacing:1.4px;font-weight:bold;color:#66748A;">NO SEU RADAR</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{''.join(cards)}</table></td></tr>
<tr><td class="content" style="padding:8px 32px 28px;">
<p style="margin:0 0 9px;font-size:14px;line-height:22px;font-weight:bold;color:#101E38;">Radar TI <span style="font-weight:normal;">| Monitor de Vagas</span></p>
<p style="margin:0 0 8px;font-size:12px;line-height:19px;color:#66748A;">Monitoramento automatizado de oportunidades em tecnologia.<br>Alerta gerado em {escape(generated_at)}.</p>
<p style="margin:0;font-size:11px;line-height:18px;color:#66748A;">As informações e os prazos podem mudar. Confira sempre os detalhes e a disponibilidade na página oficial antes de se candidatar.</p>
</td></tr></table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table></body></html>'''
