"""Build the INTEGRATION variant of the Campus AI Companion: ``python -m campus_ai.companion_build [dest]``.

``companion/`` (validated on the real AEDB) stays the preview build, WITHOUT ``nativeMessaging``. This
copies the same ``src/`` files and writes a manifest that adds only ``nativeMessaging`` (same key, hence
the same extension id that the host accepts). Default destination: ``dist/companion-integracao`` (ignored
by Git). It writes files only; it does not install, register or load anything.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'companion'
DEFAULT_DEST = ROOT / 'dist' / 'companion-integracao'
SUFFIXES = {'.js', '.html', '.css'}


def integration_manifest(preview: dict) -> dict:
    manifest = dict(preview)
    if 'nativeMessaging' in preview['permissions']:
        raise ValueError('O manifesto de pré-visualização não deve ter nativeMessaging.')
    manifest['permissions'] = [*preview['permissions'], 'nativeMessaging']
    manifest['name'] = 'Campus AI Companion (integração local)'
    manifest['description'] = ('Rascunho local, não publicado. Pré-visualiza a seção Atividades Avaliativas da AEDB '
                               'e, só quando você clica em Salvar, envia a leitura ao aplicativo Campus AI deste '
                               'computador. Não altera nada no Moodle.')
    return manifest


def build(dest: Path = DEFAULT_DEST, *, source: Path = SOURCE) -> Path:
    dest = Path(dest).resolve()
    source = Path(source).resolve()
    if dest == source or source in dest.parents:
        raise ValueError('O destino não pode ficar dentro da pasta companion/.')
    if dest.exists() and any(dest.iterdir()):
        if not (dest / 'manifest.json').is_file():
            raise ValueError('O destino existe e não é uma montagem anterior do Companion.')
        shutil.rmtree(dest)
    (dest / 'src').mkdir(parents=True, exist_ok=True)
    preview = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    for path in sorted((source / 'src').iterdir()):
        if path.is_file() and path.suffix in SUFFIXES:
            shutil.copy2(path, dest / 'src' / path.name)
    (dest / 'manifest.json').write_text(json.dumps(integration_manifest(preview), indent=2, ensure_ascii=False) + '\n',
                                        encoding='utf-8')
    return dest


if __name__ == '__main__':
    out = build(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DEST)
    print(f'Companion (integração) montado em: {out}')
