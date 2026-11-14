"""Gerar prévias fictícias offline, sem banco, credenciais ou SMTP.

Uso: python preview_email.py --output /caminho/radar-ti-preview.html
"""
import argparse
import datetime as dt
from email.message import EmailMessage
from pathlib import Path

from email_template import render_html, render_plain, subject
from monitor import FIELDS

EXAMPLE_DOMAINS = ['example.com']


def example_rows():
    deadline = (dt.date.today() + dt.timedelta(days=20)).strftime('%d/%m/%Y')
    return [
        ('example-1', 'example-v1', dict(
            title='Estágio em Governança de TI (FICTÍCIA)', company='Horizonte & Dados (empresa fictícia)',
            location='Belo Horizonte/MG', modality='Híbrido', area='Governança de TI',
            salary='R$ 1.800,00', deadline=deadline,
            activities='Apoio à gestão de acessos, inventário de ativos, documentação de processos e acompanhamento de indicadores de TI.',
            compatibility='O curso de Sistemas de Informação é aceito. As atividades de governança e documentação estão alinhadas ao seu perfil; confirme o período exigido.',
            official=True, url='https://example.com/radar-ti/vaga-ficticia-1',
            application_url='https://example.com/radar-ti/vaga-ficticia-1',
        ), False),
        ('example-2', 'example-v2', dict(
            title='Técnico de Suporte N1 (FICTÍCIA)', company='Aurora Sistemas (empresa fictícia)',
            location='Contagem/MG', modality='Presencial', area='Suporte / Service Desk',
            salary='Não informado / precisa confirmar', deadline=deadline,
            activities='Atendimento a chamados, configuração de estações de trabalho e apoio na resolução de incidentes de redes e sistemas.',
            compatibility='Vaga de entrada em suporte, sem exigência de graduação concluída. A localização e as atividades correspondem ao perfil monitorado.',
            official=True, url='https://example.com/radar-ti/vaga-ficticia-2',
            application_url='https://example.com/radar-ti/vaga-ficticia-2',
        ), True),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rows = example_rows()
    domains = EXAMPLE_DOMAINS
    generated = dt.datetime.now(dt.timezone.utc).strftime('%d/%m/%Y às %H:%M UTC')
    html = render_html(rows, generated + ' · Prévia com dados fictícios', domains)
    plain = 'PRÉVIA COM DADOS FICTÍCIOS — links ilustrativos, não representam vagas reais.\n' + render_plain(rows, FIELDS, domains)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding='utf-8')
    args.output.with_suffix('.txt').write_text(plain, encoding='utf-8')
    message = EmailMessage()
    message['Subject'] = subject(rows)
    message['From'] = 'radar@example.test'
    message['To'] = 'preview@example.test'
    message.set_content(plain)
    message.add_alternative(html, subtype='html')
    args.output.with_suffix('.eml').write_bytes(message.as_bytes())
    print(f'Prévia fictícia criada: {args.output.resolve()}')


if __name__ == '__main__':
    main()
