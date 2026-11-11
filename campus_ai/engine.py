"""Orchestrates independent connectors, idempotent writes and dashboard."""
from __future__ import annotations
from dataclasses import dataclass
from .config import Settings, app_dir
from .demo import sample_items
from .models import AcademicItem
from .state import History
from .obsidian import ObsidianWriter, NoteModifiedError


@dataclass
class ScanResult:
    items: list[AcademicItem]
    new_items: list[AcademicItem]
    warnings: list[str]
    notes_written: int
    important_items: list[AcademicItem]


def run_scan(settings: Settings, *, browser_scan=None) -> ScanResult:
    if not settings.vault_path:
        raise ValueError('Selecione o diretório de um vault Obsidian em Configurações.')
    writer = ObsidianWriter(settings.vault_path)
    history = History(app_dir() / ('demo.db' if settings.mode == 'demo' else 'live.db'))
    warnings: list[str] = []
    items: list[AcademicItem] = []
    moodle_complete = True
    if settings.mode == 'demo':
        items = sample_items()
    else:
        if settings.moodle_method == 'browser':
            try:
                from .moodle_browser import MoodleBrowserClient
                result = (browser_scan() if browser_scan is not None else
                          MoodleBrowserClient(settings.moodle_url).scan(
                              max_courses=1, course_id=settings.moodle_course_id))
                items.extend(result.items)
                warnings.extend(result.warnings)
                moodle_complete = result.complete
            except Exception as exc:
                moodle_complete = False
                warnings.append(f'Moodle via navegador indisponível ({exc.__class__.__name__}); verifique a sessão manual.')
        else:
            from .security import get_secret
            token = get_secret('moodle-token')
            if token:
                try:
                    from .moodle import MoodleClient
                    result = MoodleClient(settings.moodle_url, token).scan()
                    items.extend(result.items)
                    warnings.extend(result.warnings)
                    moodle_complete = result.complete
                except Exception as exc:
                    moodle_complete = False
                    warnings.append(f'Moodle indisponível ({exc.__class__.__name__}); verifique token, API e permissões.')
            else:
                moodle_complete = False
                warnings.append('Moodle não conectado: configure um token de API autorizado.')
        try:
            from .gmail import gmail_enabled, scan_gmail
            if gmail_enabled():
                items.extend(scan_gmail(settings.gmail_query, int(settings.max_emails)))
            else:
                warnings.append('Gmail não conectado: autorize pelo navegador em Configurações.')
        except Exception as exc:
            warnings.append(f'Gmail indisponível ({exc.__class__.__name__}); confira autorização e rede.')
    new_items: list[AcademicItem] = []
    important_items: list[AcademicItem] = []
    if not moodle_complete:
        warnings.append('Leitura Moodle parcial: notas anteriores serão preservadas até uma sincronização completa.')
    for item in items:
        if item.source == 'moodle' and not moodle_complete and history.has_uid(item.uid):
            # Partial responses must not replace a previously complete record.
            continue
        if history.changed(item):
            # Persist successful writes only, so a crashed sync is retryable.
            try:
                writer.sync_item(item)
            except NoteModifiedError:
                warnings.append('Uma nota existente foi preservada; revise alterações pessoais em Campus AI/.')
                continue
            history.remember(item)
            new_items.append(item)
            if item.source == 'gmail' and item.meta.get('important') and not history.alert_seen(item.uid):
                history.remember_alert(item.uid)
                important_items.append(item)
    notes_written = len(new_items)
    dashboard_path = writer.root / 'Painel Acadêmico.md'
    if moodle_complete or not dashboard_path.exists():
        try:
            writer.dashboard(items, warnings)
            notes_written += 1
        except NoteModifiedError:
            warnings.append('O painel existente foi preservado; revise alterações pessoais em Campus AI/.')
    history.record_scan(len(items), len(new_items), len(warnings))
    if settings.mode == 'live':
        history.record_moodle_scan(moodle_complete, sum(item.source == 'moodle' for item in items))
    return ScanResult(items, new_items, warnings, notes_written, important_items)
