"""No secrets are written to config.json."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os
import sys

APP_NAME = "CampusAI"
MOODLE_URL = "https://ead.aedb.br/ava"


def app_dir() -> Path:
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home())))
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share')))
    result = base / APP_NAME
    result.mkdir(parents=True, exist_ok=True)
    return result


@dataclass
class Settings:
    mode: str = 'demo'
    moodle_url: str = MOODLE_URL
    moodle_method: str = 'api'
    vault_path: str = ''
    gmail_credentials_path: str = ''
    gmail_query: str = 'newer_than:14d'
    max_emails: int = 30
    periodic_enabled: bool = False
    periodic_minutes: int = 60
    moodle_course_id: str = ''

    @classmethod
    def load(cls) -> 'Settings':
        path = app_dir() / 'config.json'
        if not path.exists():
            return cls()
        values = json.loads(path.read_text(encoding='utf-8'))
        return cls(**{key: values[key] for key in cls.__dataclass_fields__ if key in values})

    def save(self) -> None:
        if self.mode not in ('demo', 'live'):
            raise ValueError('Modo inválido')
        if self.moodle_method not in ('api', 'browser'):
            raise ValueError('Método Moodle inválido')
        if not self.moodle_url.startswith('https://'):
            raise ValueError('O Moodle deve usar HTTPS')
        if not (1 <= int(self.max_emails) <= 100):
            raise ValueError('Máximo de e-mails deve ficar entre 1 e 100')
        if not (15 <= int(self.periodic_minutes) <= 1440):
            raise ValueError('Intervalo de análises deve ficar entre 15 e 1440 minutos')
        if self.moodle_course_id and not self.moodle_course_id.isdecimal():
            raise ValueError('ID da disciplina deve conter somente números')
        dest = app_dir() / 'config.json'
        tmp = dest.with_suffix('.tmp')
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(dest)
