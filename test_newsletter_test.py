import contextlib
from email import policy
from email.parser import BytesParser
import io
import os
import sqlite3
import unittest
from unittest.mock import patch

import monitor
import send_newsletter_test as sender


def authorized_env():
    return dict(
        GITHUB_ACTIONS='true', GITHUB_REPOSITORY=sender.REPOSITORY,
        GITHUB_EVENT_NAME='workflow_dispatch', GITHUB_REF='refs/heads/main',
        GITHUB_RUN_ATTEMPT='1', RADAR_TEST_CONFIRMATION=sender.CONFIRMATION,
        GITHUB_SHA='a' * 40, RADAR_TEST_REVIEWED_SHA='a' * 40,
        GITHUB_WORKFLOW_REF=f'{sender.REPOSITORY}/{sender.WORKFLOW_PATH}@refs/heads/main',
        SMTP_USER='recipient@example.test', SMTP_PASSWORD='DUMMY-TEST-PASSWORD')


class IsolatedNewsletterTests(unittest.TestCase):
    def test_message_contains_only_two_fictional_jobs_and_reserved_links(self):
        msg = sender.build_message('recipient@example.test')
        parsed = BytesParser(policy=policy.default).parsebytes(msg.as_bytes())
        self.assertEqual(str(parsed['Subject']), '[TESTE] Radar TI | Prévia da newsletter')
        self.assertEqual([part.get_content_type() for part in parsed.iter_parts()],
                         ['text/plain', 'text/html'])
        plain, html = [parsed.get_body((kind,)).get_content() for kind in ['plain', 'html']]
        self.assertIn('TESTE ISOLADO', plain)
        self.assertIn('TESTE ISOLADO', html)
        self.assertEqual(html.count('Ver vaga e candidatar-se'), 2)
        self.assertEqual(html.count('(FICTÍCIA)'), 2)
        self.assertEqual(html.count('href="https://example.com/radar-ti/'), 2)
        self.assertNotIn('gupy.io', html)
        self.assertEqual(str(parsed['To']), 'recipient@example.test')
        self.assertEqual(str(parsed['From']), str(parsed['To']))

    def test_single_recipient_validation(self):
        for recipient in ['', 'invalid', 'one@example.test,two@example.test',
                          'Name <one@example.test>', 'one@example.test\nBcc:x@example.test']:
            with self.subTest(recipient=recipient), self.assertRaises(ValueError):
                sender.build_message(recipient)

    def test_every_guard_fails_before_network(self):
        for key in authorized_env():
            env = authorized_env()
            env.pop(key)
            with self.subTest(missing=key), patch.object(sender.smtplib, 'SMTP_SSL') as smtp:
                with self.assertRaises(ValueError):
                    sender.send_once(env)
                smtp.assert_not_called()
        for key, value in [('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_EVENT_NAME', 'schedule'),
                           ('GITHUB_REF', 'refs/heads/other'), ('RADAR_TEST_CONFIRMATION', 'NAO-ENVIAR'),
                           ('RADAR_TEST_REVIEWED_SHA', 'b' * 40)]:
            env = authorized_env()
            env[key] = value
            with self.subTest(guard=key), patch.object(sender.smtplib, 'SMTP_SSL') as smtp:
                with self.assertRaises(ValueError):
                    sender.send_once(env)
                smtp.assert_not_called()

    def test_one_send_without_database_collection_or_remote_state(self):
        env = authorized_env()
        # Tentativas de alterar o destinatário por variáveis externas são ignoradas.
        env.update(MAIL_TO='other@example.test', SMTP_HOST='other.example.test')
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('Banco proibido')), \
             patch.object(monitor, 'get', side_effect=AssertionError('Coleta proibida')), \
             patch.object(monitor, 'dispatch', side_effect=AssertionError('Dispatch proibido')), \
             patch('urllib.request.urlopen', side_effect=AssertionError('Estado remoto proibido')), \
             patch.object(sender.smtplib, 'SMTP_SSL') as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.return_value = {}
            result = sender.send_once(env)
            self.assertIn('SMTP aceitou uma mensagem', result)
            factory.assert_called_once()
            self.assertEqual(factory.call_args.args, ('smtp.gmail.com', 465))
            smtp.login.assert_called_once_with(env['SMTP_USER'], env['SMTP_PASSWORD'])
            smtp.send_message.assert_called_once()
            kwargs = smtp.send_message.call_args.kwargs
            self.assertEqual(kwargs['to_addrs'], [env['SMTP_USER']])
            self.assertEqual(kwargs['from_addr'], env['SMTP_USER'])

    def test_smtp_timeout_has_no_retry(self):
        with patch.object(sender.smtplib, 'SMTP_SSL') as factory:
            smtp = factory.return_value.__enter__.return_value
            smtp.send_message.side_effect = TimeoutError('PRIVATE-SERVER-RESPONSE')
            with self.assertRaises(TimeoutError):
                sender.send_once(authorized_env())
            smtp.send_message.assert_called_once()
            factory.assert_called_once()

    def test_missing_secrets_and_invalid_recipient_block_send(self):
        for key, value in [('SMTP_PASSWORD', ''), ('SMTP_USER', 'PREENCHA'),
                           ('SMTP_USER', 'invalid-recipient')]:
            env = authorized_env()
            env[key] = value
            with self.subTest(key=key, value=value), patch.object(sender.smtplib, 'SMTP_SSL') as factory:
                with self.assertRaises(ValueError):
                    sender.send_once(env)
                factory.assert_not_called()

    def test_cli_default_never_reads_secrets_or_sends(self):
        with patch.object(os, 'environ', {}), patch.object(sender, 'send_once') as send, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(sender.main([]), 0)
            send.assert_not_called()
            self.assertIn('Nenhum envio solicitado', output.getvalue())

    def test_cli_errors_never_print_sensitive_values(self):
        env = authorized_env()
        response = 'PRIVATE-SERVER-RESPONSE ' + env['SMTP_USER'] + env['SMTP_PASSWORD']
        with patch.dict(os.environ, env, clear=True), \
             patch.object(sender.smtplib, 'SMTP_SSL', side_effect=RuntimeError(response)), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(sender.main(['--send']), 1)
            for private in [response, env['SMTP_USER'], env['SMTP_PASSWORD']]:
                self.assertNotIn(private, output.getvalue())


if __name__ == '__main__':
    unittest.main()
