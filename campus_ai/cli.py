"""Testable command entry: GUI, demo smoke scan, or scheduled startup prompt."""
from __future__ import annotations
import argparse


def main():
    from .config import app_dir
    from .instance import InstanceGuard
    guard = InstanceGuard(app_dir())
    if not guard.acquire():
        print('Campus AI já está em execução. Abra a interface pelo ícone da bandeja.')
        return 1
    try:
        return _main()
    finally:
        guard.release()


def _main():
    parser = argparse.ArgumentParser(description='Campus AI — Moodle + Gmail + Obsidian')
    parser.add_argument('--startup', action='store_true', help='Mostrar pergunta de análise ao iniciar Windows')
    parser.add_argument('--pilot', action='store_true', help='Abrir no piloto, com agenda e análise completa suspensas')
    parser.add_argument('--scan', action='store_true', help='Executar sincronização usando configuração atual, sem GUI')
    parser.add_argument('--check-moodle', action='store_true',
                        help='Consultar somente informações do serviço Moodle com token já autorizado')
    parser.add_argument('--check-browser-local', action='store_true',
                        help='Abrir somente about:blank no perfil exclusivo do Campus AI')
    args = parser.parse_args()
    if args.pilot and (args.scan or args.check_moodle or args.check_browser_local or args.startup):
        parser.error('--pilot deve ser usado sozinho; nenhuma análise ou diagnóstico será iniciado.')
    if args.check_browser_local:
        from .config import Settings
        from .moodle_browser import MoodleBrowserClient
        try:
            ok = MoodleBrowserClient(Settings.load().moodle_url).smoke_local()
        except Exception as exc:
            print(f'Navegador local indisponível ({exc.__class__.__name__}); confira o perfil e o README.')
            return 1
        print('Perfil persistente e navegador local: OK.' if ok else 'Navegador local não abriu about:blank.')
        return 0 if ok else 1
    if args.check_moodle:
        from .config import Settings
        from .security import get_secret
        token = get_secret('moodle-token')
        if not token:
            print('Token Moodle autorizado não configurado. Nenhuma conexão foi feita.')
            return 1
        try:
            from .moodle import MoodleClient
            access = MoodleClient(Settings.load().moodle_url, token).probe()
        except Exception as exc:
            print(f'Consulta Moodle indisponível ({exc.__class__.__name__}). Confira token e permissões.')
            return 1
        print('Web service Moodle respondeu ao token autorizado.')
        if access.available_functions:
            print('Funções anunciadas:', ', '.join(access.available_functions))
        if access.missing_functions:
            print('Funções não anunciadas:', ', '.join(access.missing_functions))
        if not access.available_functions and not access.missing_functions:
            print('O serviço não informou a lista de funções; confirme com a instituição.')
        print('A execução de cada função ainda deve ser verificada em uma análise autorizada.')
        return 0
    if args.scan:
        from .config import Settings
        from .engine import run_scan
        result = run_scan(Settings.load())
        print(f'Itens: {len(result.items)}, novos/alterados: {len(result.new_items)}')
        for warning in result.warnings:
            print('Aviso:', warning)
        return
    from .ui import launch
    if args.pilot:
        launch(pilot=True)
    else:
        launch(startup=args.startup)


if __name__ == '__main__':
    main()
