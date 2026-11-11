"""Courses the student explicitly authorized the pilot to read.

Local file only; no network and no credentials. The AEDB course URL is always
rebuilt from a numeric id, never taken from page content. A future
"analisar minha faculdade" would iterate this list sequentially; nothing here
(or anywhere yet) starts a multi-course scan.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path

from .config import app_dir

MAX_COURSES = 50
_ID = re.compile(r'[1-9][0-9]{0,9}')


@dataclass(frozen=True)
class AuthorizedCourse:
    course_id: str
    name: str

    def __post_init__(self):
        if not isinstance(self.course_id, str) or not _ID.fullmatch(self.course_id):
            raise ValueError('ID de disciplina inválido.')
        name = ' '.join(str(self.name).split())
        if not name or len(name) > 200:
            raise ValueError('Nome de disciplina inválido.')
        object.__setattr__(self, 'name', name)

    @property
    def url(self) -> str:
        return 'https://ead.aedb.br/ava/course/view.php?id=' + self.course_id


# Authorized by the student on 05/11/2026 for the first real validation.
DEFAULT_COURSES = (AuthorizedCourse('7653', 'Modelagem UML'),)


def authorized_path() -> Path:
    return app_dir() / 'authorized_courses.json'


def load(path: Path | None = None) -> list[AuthorizedCourse]:
    path = path or authorized_path()
    try:
        values = json.loads(path.read_text(encoding='utf-8'))['courses']
        if not isinstance(values, list):
            raise TypeError
    except FileNotFoundError:
        return list(DEFAULT_COURSES)
    except (OSError, ValueError, KeyError, TypeError):
        # A damaged file must never widen the authorization.
        return list(DEFAULT_COURSES)
    courses: list[AuthorizedCourse] = []
    for value in values[:MAX_COURSES]:
        try:
            course = AuthorizedCourse(value['id'], value['name'])
        except (ValueError, KeyError, TypeError):
            continue
        if all(course.course_id != other.course_id for other in courses):
            courses.append(course)
    return courses


def save(courses, path: Path | None = None) -> None:
    courses = list(courses)
    if len(courses) > MAX_COURSES or len({c.course_id for c in courses}) != len(courses):
        raise ValueError('Lista de disciplinas autorizadas inválida.')
    path = path or authorized_path()
    tmp = path.with_suffix('.tmp')
    payload = {'courses': [{'id': c.course_id, 'name': c.name} for c in courses]}
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)
