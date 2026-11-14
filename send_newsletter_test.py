"""Teste SMTP manual isolado. Não usa dispatch, banco ou persistência remota.

Sem --send, verifica apenas a composição da mensagem, sem ler Secrets ou enviar.
"""
import argparse
import datetime as dt
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import os
import re
import smtplib
import ssl

from email_template import render_html, render_plain
from monitor import FIELDS  # Somente rótulos; importar monitor não abre banco ou rede.
from preview_email import EXAMPLE_DOMAINS, example_rows

SUBJECT = '[TESTE] Radar TI | Prévia da newsletter'
CONFIRMATION = 'ENVIAR-UM-TESTE'
REPOSITORY = 'ramondrte/vagas-ti-monitor'
WORKFLOW_PATH = '.github/workflows/test-newsletter.yml'


def build_message(recipient):
    # Proibir listas, display names e injeção de cabeçalhos; uma única conta.
    if not isinstance(recipient, str) or not recipient or re.search(r'[\s,;<>]', recipient):
        raise ValueError('Destinatário inválido')
    address = Address(addr_spec=recipient)
    if not address.username or not address.domain or '.' not in address.domain:
        raise ValueError('Destinatário inválido')
    rows = example_rows()
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%d/%m/%Y às %H:%M UTC')
    plain = ('TESTE ISOLADO — duas vagas fictícias, sem relação com anúncios reais. '
             'Links em example.com são apenas ilustrativos.\n'
             + render_plain(rows, FIELDS, EXAMPLE_DOMAINS))
    html = render_html(rows, stamp + ' · TESTE ISOLADO: duas vagas fictícias', EXAMPLE_DOMAINS)
    # Aviso visível no início, antes dos cards, sem depender de preheader oculto.
    notice = ('<p style="margin:0;padding:16px;background-color:#FFF3DF;color:#805000;'
              'font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:22px;'
              'text-align:center;"><strong>TESTE ISOLADO — DUAS VAGAS FICTÍCIAS.</strong> '
              'Empresas e links são ilustrativos. Não se candidate por esta prévia.</p>')
    body_start = html.index('>', html.index('<body')) + 1
    html = html[:body_start] + notice + html[body_start:]
    msg = EmailMessage(policy=policy.SMTP)
    msg['Subject'] = SUBJECT
    msg['From'] = recipient
    msg['To'] = recipient
    msg['Message-ID'] = make_msgid(domain='radar-ti.example')
    msg['Date'] = formatdate(localtime=False)
    msg['Auto-Submitted'] = 'auto-generated'
    msg.set_content(plain)
    msg.add_alternative(html, subtype='html')
    return msg


def check_authorization(env):
    expected = {
        'GITHUB_ACTIONS': 'true',
        'GITHUB_REPOSITORY': REPOSITORY,
        'GITHUB_EVENT_NAME': 'workflow_dispatch',
        'GITHUB_REF': 'refs/heads/main',
        'GITHUB_RUN_ATTEMPT': '1',
        'RADAR_TEST_CONFIRMATION': CONFIRMATION,
    }
    if any(env.get(key) != value for key, value in expected.items()):
        raise ValueError('Envio permitido somente no workflow manual confirmado, na primeira tentativa')
    sha = env.get('GITHUB_SHA', '')
    if not re.fullmatch(r'[0-9a-f]{40}', sha) or env.get('RADAR_TEST_REVIEWED_SHA') != sha:
        raise ValueError('SHA revisado não corresponde ao código executado')
    expected_ref = f'{REPOSITORY}/{WORKFLOW_PATH}@refs/heads/main'
    if env.get('GITHUB_WORKFLOW_REF') != expected_ref:
        raise ValueError('Workflow de origem não autorizado')


def send_once(env):
    check_authorization(env)
    user, password = env.get('SMTP_USER', ''), env.get('SMTP_PASSWORD', '')
    if not user or not password or user.startswith('PREENCHA') or password.startswith('PREENCHA'):
        raise ValueError('Secrets SMTP ausentes ou inválidos')
    # Destinatário e remetente são exclusivamente SMTP_USER, como no monitor atual.
    # MAIL_TO, MAIL_FROM e configurações locais não são utilizados.
    msg = build_message(user)
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30, context=context) as server:
        server.login(user, password)
        # Exatamente uma chamada; nenhuma repetição automática após erro ou timeout.
        refused = server.send_message(msg, from_addr=user, to_addrs=[user])
        if refused:
            raise RuntimeError('Destinatário recusado')
    return 'SMTP aceitou uma mensagem de teste para a própria conta configurada; confira o Gmail e o Spam.'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true')
    args = parser.parse_args(argv)
    if not args.send:
        msg = build_message('preview@example.test')
        assert msg.get_content_type() == 'multipart/alternative'
        print('Composição verificada offline: duas vagas fictícias, texto e HTML. Nenhum envio solicitado.')
        return 0
    try:
        result = send_once(os.environ)
    except Exception:
        # Não imprimir exceções SMTP, endereços, mensagens do servidor ou Secrets.
        print('Teste interrompido. Nenhuma retentativa automática. Se houve contato SMTP, confira Enviados antes de autorizar outro disparo.')
        return 1
    print(result)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
