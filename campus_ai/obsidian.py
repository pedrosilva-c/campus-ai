"""Writes only within an explicitly selected vault /Campus AI subfolder."""
from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from hashlib import sha1, sha256
from pathlib import Path
from urllib.parse import urlparse
import os
import re
import tempfile
from .models import AcademicItem


def slug(text: str) -> str:
    safe = re.sub(r'[^\w\- ]', ' ', text, flags=re.UNICODE)
    return re.sub(r'\s+', '-', safe).strip('-')[:65] or 'Sem-nome'


def safe_link(url: str) -> str:
    if not url:
        return ''
    parsed = urlparse(url)
    return url if parsed.scheme == 'https' and parsed.hostname else ''


def safe_text(text: str) -> str:
    return str(text or '').replace('\x00', '').strip()[:12000]


class NoteModifiedError(RuntimeError):
    """An existing note cannot be proven to be unmodified app output."""


_MARKER = '<!-- Campus AI generated sha256:'


def atomic_write(path: Path, contents: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = f'{_MARKER}{sha256(contents.encode("utf-8")).hexdigest()} -->\n'
    output = marker + contents
    if path.is_symlink():
        raise NoteModifiedError('Caminho da nota é um link simbólico.')
    if path.exists():
        previous = path.read_text(encoding='utf-8')
        if previous == output:
            return
        first, separator, body = previous.partition('\n')
        old_hash = first.removeprefix(_MARKER).removesuffix(' -->')
        if not (separator and first.startswith(_MARKER) and
                re.fullmatch(r'[0-9a-f]{64}', old_hash) and
                sha256(body.encode('utf-8')).hexdigest() == old_hash):
            raise NoteModifiedError('Nota existente preservada por conter alterações ou formato antigo.')
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                     prefix='.campus-ai-', suffix='.tmp', delete=False) as stream:
        tmp = Path(stream.name)
        stream.write(output)
    try:
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class ObsidianWriter:
    def __init__(self, vault: str):
        root = Path(vault).expanduser().resolve()
        if not root.is_dir():
            raise ValueError('A pasta do vault selecionado não existe.')
        self.root = root / 'Campus AI'
        if self.root.is_symlink():
            raise ValueError('A pasta Campus AI não pode ser um link simbólico.')
        self.root.mkdir(parents=True, exist_ok=True)

    def _check_path(self, path: Path):
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Caminho fora da pasta Campus AI.')

    def filename_for(self, item: AcademicItem) -> Path:
        folder = 'Emails' if item.category == 'message' else 'Disciplinas'
        course = slug(item.course)
        short_id = sha1(item.uid.encode('utf8')).hexdigest()[:10]
        name = f'{slug(item.title)}-{short_id}.md'
        parent = self.root / folder / course
        # Keep the same note when an activity's title changes in the source.
        existing = sorted(parent.glob(f'*-{short_id}.md')) if parent.is_dir() else []
        if existing:
            return existing[0]  # Preserve notes written before type subfolders.
        kind = {'material': 'Materiais', 'assignment': 'Atividades', 'announcement': 'Comunicados',
                'message': 'Mensagens'}.get(item.category, 'Outros')
        typed = parent / kind
        existing = sorted(typed.glob(f'*-{short_id}.md')) if typed.is_dir() else []
        return existing[0] if existing else typed / name

    def sync_item(self, item: AcademicItem) -> Path:
        path = self.filename_for(item)
        self._check_path(path)
        target = safe_link(item.url)
        # Link is displayed as a plain URL, not as executable markup.
        lines = [
            f'# {safe_text(item.title)}', '',
            '> [!info] Nota gerada automaticamente pelo Campus AI',
            '> Evite editar este arquivo; crie anotações pessoais em outra nota.', '',
            f'**Disciplina:** {safe_text(item.course)}',
            f'**Origem:** {safe_text(item.source)}',
            f'**Categoria:** {safe_text(item.category)}',
            f'**Estado:** {safe_text(item.status)}',
        ]
        if item.due_iso:
            lines.append(f'**Prazo informado:** {safe_text(item.due_iso)}')
        if item.meta.get('teacher') or item.meta.get('sender'):
            lines.append(f'**Professor/remetente:** {safe_text(item.meta.get("teacher") or item.meta["sender"])}')
        if item.meta.get('published_iso'):
            lines.append(f'**Publicação informada:** {safe_text(item.meta["published_iso"])}')
        elif item.meta.get('source_added_iso'):
            lines.append(f'**Data de inclusão informada pela fonte:** {safe_text(item.meta["source_added_iso"])}')
        if target:
            lines.append(f'**Abrir fonte:** {target}')
        lines += ['', '## Resumo', '',
                  (safe_text(item.description)[:500] + ('…' if len(item.description) > 500 else ''))
                  if item.description else '_Conteúdo não informado._',
                  '', '_Trecho da fonte; sem interpretação por IA._',
                  '', '## Tarefas a realizar', '']
        if item.category == 'assignment' and item.status != 'submitted':
            lines += ['- [ ] Conferir o enunciado e o prazo na fonte original.',
                      '- [ ] Registrar a resolução em uma nota pessoal e realizar a entrega manualmente.']
        elif item.status == 'submitted':
            lines.append('Fonte indica envio realizado; isso não informa correção ou aprovação.')
        else:
            lines.append('_Nenhuma tarefa específica identificada._')
        lines += ['', '## Enunciado / conteúdo identificado', '', safe_text(item.description) or '_Sem descrição disponível na fonte._',
                  '', '## Meu estudo', '', '> Crie uma nota pessoal vinculada a esta página para registrar sua resolução.', '']
        atomic_write(path, '\n'.join(lines))
        return path

    def dashboard(self, items: list[AcademicItem], errors: list[str]):
        grouped: dict[str, list[AcademicItem]] = defaultdict(list)
        for item in items:
            grouped[item.course].append(item)
        lines = ['# Painel Acadêmico — Campus AI', '',
                 f'_Última sincronização: {datetime.now().strftime("%d/%m/%Y %H:%M")}_', '',
                 '> [!warning] Prazo e envio de atividades',
                 '> Confirme sempre as datas e o estado de entrega no Moodle original.', '']
        for course in sorted(grouped):
            lines += [f'## {safe_text(course)}', '']
            for item in sorted(grouped[course], key=lambda x: (x.due_iso or '9999', x.title)):
                rel = self.filename_for(item).relative_to(self.root).with_suffix('').as_posix()
                due = f' | prazo: {item.due_iso[:16]}' if item.due_iso else ''
                lines.append(f'- [[{rel}|{safe_text(item.title)}]] — {item.category} ({item.status}){due}')
            lines.append('')
        if errors:
            lines += ['## Conectores com problemas', '']
            for err in errors:
                lines.append(f'- {safe_text(err)}')
            lines.append('')
        path = self.root / 'Painel Acadêmico.md'
        self._check_path(path)
        atomic_write(path, '\n'.join(lines))
