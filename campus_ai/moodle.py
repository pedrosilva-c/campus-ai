"""Read-only Moodle REST adapter. Requires an authorized, pre-issued service token."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
import requests
from .models import AcademicItem

READ_FUNCTIONS = (
    'core_webservice_get_site_info',
    'core_enrol_get_users_courses',
    'core_course_get_contents',
    'mod_assign_get_assignments',
    'mod_assign_get_submission_status',
)


class MoodleAuthenticationError(RuntimeError):
    """The service token was rejected."""


class MoodleConnectionError(RuntimeError):
    """The authorized web service could not be reached."""


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def plain(html: str) -> str:
    parser = _Text()
    parser.feed(str(html or ''))
    return ' '.join(' '.join(parser.parts).split())[:12000]


def unix_date(value) -> str:
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).astimezone().isoformat(timespec='minutes') if value else ''
    except (ValueError, TypeError, OSError, OverflowError):
        return ''


@dataclass
class MoodleScan:
    items: list[AcademicItem]
    warnings: list[str]
    complete: bool


@dataclass
class MoodleAccess:
    user_id: int
    available_functions: tuple[str, ...]
    missing_functions: tuple[str, ...]
    complete: bool


class MoodleClient:
    def __init__(self, base_url: str, token: str, session=None):
        parsed = urlparse(base_url.rstrip('/'))
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('URL Moodle inválida: use somente endereço HTTPS do portal.')
        if not token or not token.strip():
            raise ValueError('Token Moodle não configurado.')
        self.base_url = base_url.rstrip('/')
        self.token = token.strip()
        self.session = session if session is not None else requests.Session()

    def call(self, function: str, params: dict | None = None):
        data = {'wstoken': self.token, 'wsfunction': function, 'moodlewsrestformat': 'json'}
        data.update(params or {})
        try:
            response = self.session.post(self.base_url + '/webservice/rest/server.php',
                                         data=data, timeout=(10, 35), allow_redirects=False)
            response.raise_for_status()
        except requests.RequestException:
            raise MoodleConnectionError('Não foi possível consultar o web service Moodle.') from None
        if response.is_redirect:
            raise RuntimeError('Moodle redirecionou requisição de API; confirme endereço e permissões.')
        try:
            result = response.json()
        except ValueError:
            raise RuntimeError('A API Moodle não retornou JSON; serviço possivelmente desativado.') from None
        if isinstance(result, dict) and 'exception' in result:
            # Server messages may echo credentials or private request details.
            if result.get('errorcode') == 'invalidtoken':
                raise MoodleAuthenticationError('Token Moodle inválido ou expirado.')
            raise RuntimeError(f'Moodle negou {function}; confira token e permissões do serviço.')
        return result

    def _site_info(self) -> dict:
        site = self.call('core_webservice_get_site_info')
        if not isinstance(site, dict) or not site.get('userid'):
            raise RuntimeError('Moodle não informou o usuário autenticado.')
        return site

    def probe(self) -> MoodleAccess:
        """Inspect advertised functions; a real scan still verifies each call."""
        site = self._site_info()
        functions = site.get('functions')
        if not isinstance(functions, list):
            return MoodleAccess(int(site['userid']), (), (), False)
        offered = {f.get('name') for f in functions if isinstance(f, dict)}
        available = tuple(name for name in READ_FUNCTIONS if name in offered)
        missing = tuple(name for name in READ_FUNCTIONS if name not in offered)
        return MoodleAccess(int(site['userid']), available, missing, not missing)

    def scan(self) -> MoodleScan:
        warnings: list[str] = []
        complete = True
        site = self._site_info()
        uid = site['userid']
        courses = self.call('core_enrol_get_users_courses', {'userid': uid})
        if not isinstance(courses, list):
            raise RuntimeError('Moodle retornou uma lista de disciplinas incompleta.')
        seen: dict[str, AcademicItem] = {}
        for course in courses:
            cid = int(course['id'])
            cname = plain(course.get('fullname') or course.get('shortname', f'Disciplina {cid}'))
            try:
                sections = self.call('core_course_get_contents', {'courseid': cid})
                for section in sections:
                    if not isinstance(section, dict) or not isinstance(section.get('modules'), list):
                        raise ValueError('Seção Moodle sem lista de módulos.')
                    for module in section['modules']:
                        if not module.get('uservisible', True):
                            continue
                        mid = module.get('id')
                        if not mid:
                            raise ValueError('Módulo Moodle sem identificador.')
                        kind = module.get('modname', '')
                        if kind not in ('resource', 'page', 'url', 'folder', 'book', 'assign', 'quiz', 'forum', 'lesson'):
                            continue
                        itemid = f'moodle:course:{cid}:module:{mid}'
                        title = plain(module.get('name', 'Material'))
                        description = plain(module.get('description', ''))
                        if not description:
                            description = plain(module.get('intro', ''))
                        file_names = [str(content.get('filename')) for content in module.get('contents', [])
                                      if content.get('filename') and content['filename'] != '.']
                        if file_names:
                            description += '\nAnexos referenciados no Moodle: ' + ', '.join(file_names[:20])
                        seen[itemid] = AcademicItem(itemid, 'moodle', 'assignment' if kind in ('assign', 'quiz') else 'material',
                            title, cname, description, module.get('url', ''), status='unknown',
                            meta={'courseid': cid, 'moduleid': mid, 'type': kind,
                                  'source_added_iso': unix_date(module.get('added'))})
            except Exception as exc:
                complete = False
                warnings.append(f'{cname}: não foi possível ler os módulos ({exc.__class__.__name__}).')
        # Due dates: mod_assign is separate from course modules and may be unavailable.
        courseids = {'courseids[%d]' % i: int(c['id']) for i, c in enumerate(courses)}
        if courseids:
            try:
                data = self.call('mod_assign_get_assignments', courseids)
                if not isinstance(data, dict) or not isinstance(data.get('courses'), list):
                    raise RuntimeError('Lista de tarefas incompleta.')
                for course in data.get('courses', []):
                    cid = int(course['id'])
                    cname = next((plain(c.get('fullname', '')) for c in courses if int(c['id']) == cid), f'Disciplina {cid}')
                    for a in course.get('assignments', []):
                        assignid = int(a['id'])
                        cmid = a.get('cmid')
                        itemid = f'moodle:course:{cid}:module:{cmid}' if cmid else f'moodle:course:{cid}:assign:{assignid}'
                        description = plain(a.get('intro', ''))
                        due = unix_date(a.get('duedate'))
                        status = 'unknown'
                        try:
                            sub = self.call('mod_assign_get_submission_status', {'assignid': assignid})
                            attempt = sub.get('lastattempt') or {}
                            submission = attempt.get('submission') or {}
                            state = submission.get('status', '')
                            if state == 'submitted':
                                status = 'submitted'
                            elif state in ('draft', 'new'):
                                status = 'pending'
                            else:
                                complete = False
                                warnings.append(f'{cname}: estado de entrega indisponível; confirme no AVA.')
                        except Exception:
                            # Don't falsely report a submission as pending.
                            complete = False
                            status = 'unknown'
                            warnings.append(f'{cname}: estado de entrega indisponível; confirme no AVA.')
                        previous = seen.get(itemid)
                        seen[itemid] = AcademicItem(itemid, 'moodle', 'assignment', plain(a.get('name', 'Atividade')),
                            cname, description or (previous.description if previous else ''),
                            (previous.url if previous else f'{self.base_url}/mod/assign/view.php?id={cmid}') if cmid else '',
                            due_iso=due, status=status,
                            meta={'courseid': cid, 'assignid': assignid, 'moduleid': cmid})
            except Exception as exc:
                complete = False
                warnings.append(f'Prazos/entregas de tarefas não disponíveis ({exc.__class__.__name__}); confirme no AVA.')
        else:
            warnings.append('Nenhuma disciplina matriculada foi retornada pela API.')
        return MoodleScan(list(seen.values()), warnings, complete)
