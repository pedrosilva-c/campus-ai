"""Local notification events; deduplicated atomically across application restarts."""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256


@dataclass(frozen=True)
class Alert:
    kind: str
    message: str


def remember(history, kind, identity, message):
    key = sha256((kind + ':' + identity).encode('utf-8')).hexdigest()
    return Alert(kind, message) if history.add_alert(key, kind, message) else None


def collect_alerts(history, result, *, now=None):
    now = now or datetime.now(timezone.utc)
    events = []
    def add(kind, identity, message):
        alert = remember(history, kind, identity, message)
        if alert:
            events.append(alert)
    for item in result.new_items:
        kind = {'assignment': 'Atividade nova ou alterada', 'material': 'Material novo ou alterado',
                'announcement': 'Novo comunicado', 'message': 'Nova mensagem'}.get(item.category, 'Novidade acadêmica')
        if item.category == 'message' and not item.meta.get('important'):
            continue
        identity = item.uid if item.category == 'message' else item.uid + ':' + item.fingerprint()
        add(kind, identity, f'{item.course}: {item.title}')
    for item in result.items:
        if not item.due_iso or item.status == 'submitted':
            continue
        try:
            due = datetime.fromisoformat(item.due_iso)
            if due.tzinfo is None:
                due = due.astimezone()
        except (ValueError, OverflowError):
            continue
        if now <= due <= now + timedelta(hours=48):
            add('Prazo próximo', item.uid + ':' + item.due_iso, f'{item.title} — {item.due_iso}')
    for warning in result.warnings:
        expired = 'SessionExpired' in warning or 'Sessão Moodle expirou' in warning
        kind = 'Sessão AEDB expirada' if expired else 'Sincronização parcial'
        add(kind, warning, 'Faça login manual pelo botão Conectar conta AEDB.' if expired else warning)
    return events
