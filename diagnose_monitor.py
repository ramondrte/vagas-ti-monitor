"""Executar somente testes, offline, com SQLite restrito a diretórios temporários.

Não chama cloud_run, coleta, dispatch ou SMTP como rotina operacional.
Os testes existentes simulam transporte e persistência; sem Secrets reais.
"""
import contextlib
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.request


def main():
    if sys.version_info[:2] != (3, 12):
        print('Diagnóstico exige Python 3.12.')
        return 1
    sys.dont_write_bytecode = True
    root = Path(__file__).resolve().parent
    blocked = []

    def deny_network(*args, **kwargs):
        blocked.append('network')
        raise RuntimeError('Rede real bloqueada no diagnóstico')

    original_sqlite = sqlite3.connect
    with tempfile.TemporaryDirectory(prefix='radar-ti-diagnostic-') as folder:
        scratch = Path(folder).resolve()
        # Apenas estes valores não sensíveis chegam à suíte; nenhum token/Secret.
        environment = {'PATH': os.environ.get('PATH', ''), 'TMPDIR': str(scratch),
                       'GITHUB_ACTIONS': 'true', 'EMAIL_ENABLED': 'false',
                       'PYTHONDONTWRITEBYTECODE': '1'}

        def only_temporary_sqlite(database, *args, **kwargs):
            if database != ':memory:':
                if not isinstance(database, (str, os.PathLike)) or not Path(database).resolve().is_relative_to(scratch):
                    blocked.append('sqlite')
                    raise RuntimeError('SQLite fora da área temporária bloqueado')
            return original_sqlite(database, *args, **kwargs)

        with contextlib.ExitStack() as guards:
            guards.enter_context(patch.dict(os.environ, environment, clear=True))
            guards.enter_context(patch.object(tempfile, 'tempdir', str(scratch)))
            for owner, name in [(socket, 'create_connection'), (socket, 'getaddrinfo'),
                                (socket.socket, 'connect'), (socket.socket, 'connect_ex'),
                                (socket.socket, 'sendto'), (urllib.request, 'urlopen')]:
                guards.enter_context(patch.object(owner, name, side_effect=deny_network))
            guards.enter_context(patch.object(sqlite3, 'connect', side_effect=only_temporary_sqlite))
            import monitor
            original_connect = monitor.connect

            def only_temporary_root(directory=None):
                if directory is None or not Path(directory).resolve().is_relative_to(scratch):
                    blocked.append('monitor-root')
                    raise RuntimeError('Raiz persistente bloqueada no diagnóstico')
                return original_connect(directory)

            guards.enter_context(patch.object(monitor, 'connect', side_effect=only_temporary_root))
            # Verificar as barreiras antes de carregar a suíte; sem criar conexão real.
            try:
                socket.create_connection(('example.com', 443))
            except RuntimeError:
                pass
            try:
                sqlite3.connect(root / 'data/diagnostic-forbidden.sqlite3')
            except RuntimeError:
                pass
            if blocked != ['network', 'sqlite']:
                print('Falha ao verificar isolamento; testes não executados.')
                return 1
            blocked.clear()
            suite = unittest.defaultTestLoader.discover(str(root), pattern='test_*.py')
            print(f'Python {sys.version.split()[0]} | suíte offline | SQLite temporário', flush=True)
            result = unittest.TextTestRunner(verbosity=1).run(suite)
            if blocked:
                print('Uma tentativa de acesso externo foi bloqueada; diagnóstico reprovado.')
                return 1
            if not result.wasSuccessful() or result.testsRun == 0:
                return 1
            print(f'Diagnóstico aprovado: {result.testsRun} testes; sem rede ou histórico persistente.')
            return 0


if __name__ == '__main__':
    raise SystemExit(main())
