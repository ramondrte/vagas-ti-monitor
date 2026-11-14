import copy
import datetime as dt
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import email_template as template
import monitor as m
from state_store import dump, restore

DOMAINS = ['gupy.io', 'jobs.lever.co']


def job():
    return dict(title='Estágio em Infraestrutura', company='Empresa & Tecnologia',
                location='Belo Horizonte/MG', modality='Híbrido', area='Infraestrutura / Cloud',
                salary='R$ 1.500', activities='Apoiar servidores e redes.',
                compatibility='Atividades de infraestrutura compatíveis com o curso.',
                deadline='30/12/2030', official=True, url='https://empresa.gupy.io/jobs/1',
                application_url='https://empresa.gupy.io/candidates/jobs/1/apply?a=1&b=2')


def row(j=None, updated=False):
    return ('id', 'fingerprint', job() if j is None else j, updated)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.urls.append(dict(attrs)['href'])


class TemplateTests(unittest.TestCase):
    def test_multiple_jobs_and_subjects(self):
        rows = [row(), row(updated=True)]
        result = template.render_html(rows, '14/11/2026 às 12:00 UTC', DOMAINS)
        self.assertEqual(result.count('Ver vaga e candidatar-se'), 2)
        self.assertIn('NOVA OPORTUNIDADE', result)
        self.assertIn('VAGA ATUALIZADA', result)
        self.assertIn('02', result)
        self.assertIn('14/11/2026 às 12:00 UTC', result)
        self.assertEqual(template.subject(rows), 'Radar TI | 1 vaga nova e 1 vaga atualizada')
        self.assertEqual(template.subject([row()]), 'Radar TI | 1 vaga nova')
        self.assertEqual(template.subject([row(updated=True)]), 'Radar TI | 1 vaga atualizada')
        self.assertEqual(template.subject([row(), row()]), 'Radar TI | 2 vagas novas')
        self.assertEqual(template.subject([row(updated=True)] * 2), 'Radar TI | 2 vagas atualizadas')

    def test_missing_fields(self):
        result = template.render_html([row({})], None, DOMAINS)
        self.assertIn(template.UNKNOWN, result)
        self.assertNotIn('Bolsa / salário:', result)
        self.assertNotIn('Inscrições até:', result)
        self.assertNotIn('<a ', result)
        self.assertNotIn('None', result)
        j = job()
        j.update(salary=template.UNKNOWN, deadline='')
        result = template.render_html([row(j)], 'agora', DOMAINS)
        self.assertNotIn('Bolsa / salário:', result)
        self.assertNotIn('Inscrições até:', result)

    def test_escape_every_dynamic_field(self):
        payload = '<script>alert("x")</script> & \' aspas'
        j = job()
        for key in ['title', 'company', 'location', 'modality', 'area', 'salary',
                    'activities', 'compatibility', 'deadline']:
            j[key] = payload
        result = template.render_html([row(j)], payload, DOMAINS)
        self.assertNotIn('<script>', result)
        self.assertEqual(result.count(template.escape(payload)), 10)
        parser = Links()
        parser.feed(result)
        self.assertEqual(parser.urls, [j['application_url']])

    def test_iso_deadline_fallback(self):
        j = job()
        j.update(deadline=template.UNKNOWN, deadline_iso='2030-12-30')
        result = template.render_html([row(j)], 'agora', DOMAINS)
        self.assertIn('Inscrições até:</strong> 2030-12-30', result)

    def test_invalid_urls(self):
        for value in [None, '', 'javascript:alert(1)', 'http://empresa.gupy.io/job',
                      '//empresa.gupy.io/job', 'https://gupy.io.evil.test/job',
                      'https://evilgupy.io/job', 'https://gupy.io@evil.test/job',
                      'https://user:pass@empresa.gupy.io/job', 'https://localhost/job',
                      'https://127.0.0.1/job', 'https://[::1]/job',
                      'https://empresa.gupy.io:444/job', 'https://empresa.gupy.io:bad/job',
                      'https://empresa.gupy.io/\njob', 'https://empresa.gupy.io/" onclick="x',
                      'https://empresa.gupy.io\\@evil.test/job', 'https://[bad/job']:
            with self.subTest(url=value):
                self.assertIsNone(template.safe_url(value, DOMAINS))
        self.assertEqual(template.safe_url('https://empresa.gupy.io/jobs/1', DOMAINS),
                         'https://empresa.gupy.io/jobs/1')

    def test_official_fallback_and_no_link_for_untrusted_job(self):
        j = job()
        j['application_url'] = 'javascript:alert(1)'
        self.assertEqual(template.application_url(j, DOMAINS), j['url'])
        j['url'] = 'https://evil.test/job'
        result = template.render_html([row(j)], 'agora', DOMAINS)
        self.assertNotIn('<a ', result)
        self.assertNotIn('javascript:', result)
        j = job()
        j['official'] = False
        self.assertIsNone(template.application_url(j, DOMAINS))
        self.assertIsNone(template.application_url(job(), []))

    def test_summary_is_bounded_and_input_not_mutated(self):
        j = job()
        j['activities'] = 'Administrar redes e servidores. ' * 40
        before = copy.deepcopy(j)
        self.assertLessEqual(len(template.summary(j['activities'])), 260)
        self.assertTrue(template.summary(j['activities']).endswith('…'))
        result = template.render_html([row(j)], 'agora', DOMAINS)
        self.assertEqual(j, before)
        for forbidden in ['<script', '<img', '<link', '@import', 'url(']:
            self.assertNotIn(forbidden, result)
        self.assertIn('max-width:600px', result)


class TransportTests(unittest.TestCase):
    def test_multipart_survives_serialization_on_both_transports(self):
        for port in ['465', '587']:
            with self.subTest(port=port):
                env = dict(GITHUB_ACTIONS='true', SMTP_HOST='smtp.example.test',
                           SMTP_USER='test@example.test', SMTP_PASSWORD='dummy', SMTP_PORT=port)
                with patch.dict(os.environ, env, clear=True), \
                     patch.object(m.smtplib, 'SMTP_SSL') as secure, \
                     patch.object(m.smtplib, 'SMTP') as starttls:
                    factory = secure if port == '465' else starttls
                    server = factory.return_value
                    server.__enter__.return_value = server
                    server.send_message.return_value = {}
                    html = template.render_html([row()], 'agora', DOMAINS)
                    mid = m.smtp_send('Radar TI | 1 vaga nova', 'Texto com acentuação & detalhes.', html_body=html)
                    msg = server.send_message.call_args.args[0]
                    parsed = BytesParser(policy=policy.default).parsebytes(msg.as_bytes())
                    self.assertEqual(parsed.get_content_type(), 'multipart/alternative')
                    self.assertEqual([part.get_content_type() for part in parsed.iter_parts()],
                                     ['text/plain', 'text/html'])
                    self.assertIn('acentuação', parsed.get_body(('plain',)).get_content())
                    self.assertIn('Ver vaga e candidatar-se', parsed.get_body(('html',)).get_content())
                    self.assertEqual(parsed['Message-ID'], mid)
                    self.assertEqual(parsed['Subject'], 'Radar TI | 1 vaga nova')
                    if port == '587':
                        server.starttls.assert_called_once()
                        secure.assert_not_called()
                    else:
                        starttls.assert_not_called()

    def test_existing_plain_test_email_still_supported(self):
        env = dict(GITHUB_ACTIONS='true', SMTP_USER='test@example.test', SMTP_PASSWORD='dummy')
        with patch.dict(os.environ, env, clear=True), patch.object(m.smtplib, 'SMTP_SSL') as factory:
            server = factory.return_value
            server.send_message.return_value = {}
            m.smtp_send('Teste', 'Mensagem de teste')
            self.assertEqual(server.send_message.call_args.args[0].get_content_type(), 'text/plain')


class DeliveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.c = m.connect(self.root)
        self.config = json.loads((m.ROOT / 'config.json').read_text())
        self.j = json.loads((m.ROOT / 'fixture_review.json').read_text())[0]
        self.j.update(verified_at=m.now(), deadline_iso=(dt.date.today() + dt.timedelta(days=30)).isoformat())
        self.c.execute('INSERT INTO candidates VALUES(?,?,?,?,?,NULL)',
                       (self.j['url'], 'test', m.now(), m.now(), json.dumps({'text': 'Candidatar-se'})))
        self.c.commit()
        m.ingest(self.c, [self.j], self.config)

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def test_dry_run_renders_both_previews_without_changing_any_table(self):
        before = dump(self.c)
        with patch.object(m, 'ROOT', self.root), patch.object(m, 'smtp_send') as smtp, \
             patch.object(m, 'fetch') as fetch:
            result = m.dispatch(self.c, self.config, False)
        self.assertFalse(result['sent'])
        smtp.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(before, dump(self.c))
        self.assertTrue((self.root / 'data/preview.html').is_file())
        self.assertIn('Cargo:', (self.root / 'data/preview.txt').read_text())
        self.assertIn('Santa Casa BH', (self.root / 'data/preview.html').read_text())
        self.assertEqual(len(m.pending(self.c, self.config)), 1)

    def test_delivery_checkpoint_order_and_no_resend_when_template_changes(self):
        checkpoints = []
        def checkpoint():
            checkpoints.append(self.c.execute('SELECT status FROM deliveries').fetchone()[0])
        fp_before = self.c.execute('SELECT fingerprint FROM jobs').fetchone()[0]
        with patch.object(m, 'ROOT', self.root), \
             patch.dict(os.environ, {'EMAIL_ENABLED': 'true', 'GITHUB_ACTIONS': 'true'}), \
             patch.object(m, 'fetch', return_value={'text': 'Candidatar-se', 'job_postings': []}), \
             patch.object(m, 'smtp_send', return_value='<mock@local>') as smtp:
            self.assertTrue(m.dispatch(self.c, self.config, True, checkpoint)['sent'])
            args, kwargs = smtp.call_args
            self.assertEqual(args[0], 'Radar TI | 1 vaga nova')
            self.assertIn('Cargo:', args[1])
            self.assertIn('Ver vaga e candidatar-se', kwargs['html_body'])
            self.assertEqual(checkpoints, ['sending', 'accepted'])
            m.ingest(self.c, [copy.deepcopy(self.j)], self.config)
            with patch.object(m, 'render_html', return_value='Outro template'):
                self.assertFalse(m.dispatch(self.c, self.config, True, checkpoint)['sent'])
            smtp.assert_called_once()
        self.assertEqual(fp_before, self.c.execute('SELECT fingerprint FROM jobs').fetchone()[0])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM sent').fetchone()[0], 1)

    def test_mixed_alert_from_sqlite_to_multipart_preserves_historical_delivery(self):
        jid, old_fp, _, _ = m.pending(self.c, self.config)[0]
        self.c.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,NULL)',
                       ('historical', m.now(), 'accepted', json.dumps([(jid, old_fp)]), '<old@local>'))
        self.c.execute('INSERT INTO sent VALUES(?,?,?,?)', (jid, old_fp, 'historical', m.now()))
        self.c.commit()
        historical = dict(self.c.execute("SELECT * FROM deliveries WHERE id='historical'").fetchone())
        updated = copy.deepcopy(self.j)
        updated['hours'] += ' (alteração simulada de jornada)'
        m.ingest(self.c, [updated], self.config)
        entry = copy.deepcopy(self.j)
        entry.update(title='Técnico de Suporte N1', kind='entry', job_id='fixture-entry',
                     url='https://fixture.gupy.io/jobs/2',
                     application_url='https://fixture.gupy.io/candidates/jobs/2/apply')
        self.c.execute('INSERT INTO candidates VALUES(?,?,?,?,?,NULL)',
                       (entry['url'], 'test', m.now(), m.now(), json.dumps({'text': 'Candidatar-se'})))
        self.c.commit()
        m.ingest(self.c, [entry], self.config)
        captured = []
        def accept_message(msg):
            # O checkpoint precisa estar durável antes de tentar entregar a mensagem.
            status = self.c.execute("SELECT status FROM deliveries WHERE id!='historical'").fetchone()[0]
            self.assertEqual(status, 'sending')
            self.assertEqual(self.c.execute('SELECT COUNT(*) FROM sent').fetchone()[0], 1)
            captured.append(BytesParser(policy=policy.default).parsebytes(msg.as_bytes()))
            return {}
        env = dict(GITHUB_ACTIONS='true', EMAIL_ENABLED='true', SMTP_USER='test@example.test',
                   SMTP_PASSWORD='dummy', SMTP_HOST='smtp.example.test', SMTP_PORT='465')
        with patch.object(m, 'ROOT', self.root), patch.dict(os.environ, env, clear=True), \
             patch.object(m, 'fetch', return_value={'text': 'Candidatar-se', 'job_postings': []}), \
             patch.object(m.smtplib, 'SMTP_SSL') as factory:
            server = factory.return_value
            server.__enter__.return_value = server
            server.send_message.side_effect = accept_message
            result = m.dispatch(self.c, self.config, True)
            self.assertTrue(result['sent'])
            self.assertEqual(result['new_jobs'], 2)
            self.assertFalse(m.dispatch(self.c, self.config, True)['sent'])
            server.send_message.assert_called_once()
        msg = captured[0]
        self.assertEqual(str(msg['Subject']), 'Radar TI | 1 vaga nova e 1 vaga atualizada')
        self.assertEqual(msg.get_content_type(), 'multipart/alternative')
        plain = msg.get_body(('plain',)).get_content()
        html = msg.get_body(('html',)).get_content()
        self.assertIn('Vaga atualizada', plain)
        self.assertIn('Vaga nova', plain)
        self.assertIn('NOVA OPORTUNIDADE', html)
        self.assertIn('VAGA ATUALIZADA', html)
        self.assertEqual(html.count('Ver vaga e candidatar-se'), 2)
        self.assertIn(entry['application_url'], html)
        self.assertIn(self.j['application_url'], html)
        self.assertIn(self.j['compatibility'], html)
        for fake in ['TESTE ISOLADO', 'Horizonte &amp; Dados', 'example.com/radar-ti/']:
            self.assertNotIn(fake, html)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM sent').fetchone()[0], 3)
        self.assertEqual(historical, dict(self.c.execute("SELECT * FROM deliveries WHERE id='historical'").fetchone()))
        snapshot = dump(self.c)
        restore(self.c, snapshot)
        self.assertEqual(dump(self.c), snapshot)
        self.assertEqual(m.pending(self.c, self.config), [])
        self.assertEqual(self.c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_uncertain_delivery_remains_blocked_after_snapshot_restore(self):
        checkpoints = []
        def checkpoint():
            checkpoints.append(self.c.execute('SELECT status FROM deliveries').fetchone()[0])
        with patch.object(m, 'ROOT', self.root), \
             patch.dict(os.environ, {'EMAIL_ENABLED': 'true', 'GITHUB_ACTIONS': 'true'}), \
             patch.object(m, 'fetch', return_value={'text': 'Candidatar-se', 'job_postings': []}), \
             patch.object(m, 'smtp_send', side_effect=TimeoutError) as smtp:
            with self.assertRaises(TimeoutError):
                m.dispatch(self.c, self.config, True, checkpoint)
            smtp.assert_called_once()
        self.assertEqual(checkpoints, ['sending', 'uncertain'])
        snapshot = dump(self.c)
        restore(self.c, snapshot)
        with patch.object(m, 'ROOT', self.root), patch.object(m, 'smtp_send') as smtp, \
             patch.object(m, 'fetch') as fetch:
            with self.assertRaisesRegex(ValueError, 'Envio anterior incerto'):
                m.dispatch(self.c, self.config, True)
            smtp.assert_not_called()
            fetch.assert_not_called()
        self.assertEqual(dump(self.c), snapshot)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM sent').fetchone()[0], 0)
        self.assertEqual(self.c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_html_render_failure_happens_before_any_delivery_or_smtp(self):
        before = dump(self.c)
        with patch.object(m, 'ROOT', self.root), \
             patch.object(m, 'render_html', side_effect=ValueError('Falha simulada no template')), \
             patch.object(m, 'smtp_send') as smtp:
            with self.assertRaises(ValueError):
                m.dispatch(self.c, self.config, True)
            smtp.assert_not_called()
        self.assertEqual(dump(self.c), before)


if __name__ == '__main__':
    unittest.main()
