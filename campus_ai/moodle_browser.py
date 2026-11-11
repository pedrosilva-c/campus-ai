"""Visible, read-only Moodle browser adapter. Playwright is loaded only on use."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
import os
import shutil
import time

from .config import app_dir
from .models import AcademicItem
from .browser_profile import verify_private_profile


class SessionExpired(RuntimeError):
    """A manual sign-in is required."""


class BrowserUnavailable(RuntimeError):
    """Playwright or its Chromium browser is not installed."""


class PortalBlocked(RuntimeError):
    """The portal explicitly refused automated access."""


@dataclass
class BrowserScan:
    items: list[AcademicItem]
    warnings: list[str]
    complete: bool


@dataclass
class Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: Node | None = None
    children: list[Node] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)

    def nodes(self):
        yield self
        for child in self.children:
            yield from child.nodes()

    def text(self):
        return ' '.join(' '.join(self.parts + [c.text() for c in self.children]).split())

    def has_class(self, name):
        return name in self.attrs.get('class', '').split()


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node('document')
        self.current = self.root
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), self.current)
        self.current.children.append(node)
        if tag not in ('area', 'base', 'br', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'wbr'):
            self.current = node

    def handle_endtag(self, tag):
        cursor = self.current
        while cursor.parent:
            if cursor.tag == tag:
                self.current = cursor.parent
                return
            cursor = cursor.parent

    def handle_data(self, data):
        self.current.parts.append(data)


class MoodleBrowserClient:
    """Separate from the token API client; never fills forms or exports cookies."""

    def __init__(self, base_url: str, *, page=None, profile_dir: Path | None = None,
                 timeout_ms: int = 15000, delay_seconds: float = 0.5, max_pages: int = 40):
        parsed = urlparse(base_url.rstrip('/'))
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('URL Moodle inválida.')
        self.base_url = base_url.rstrip('/')
        self.origin = (parsed.scheme, parsed.netloc)
        self.base_path = parsed.path.rstrip('/') + '/'
        self.profile_dir = Path(profile_dir) if profile_dir else app_dir() / 'browser_profile'
        self.page = page
        self.timeout_ms = timeout_ms
        self.delay_seconds = delay_seconds
        self.max_pages = max_pages

    def _url(self, href: str) -> str:
        url = urljoin(self.base_url + '/', href)
        parsed = urlparse(url)
        if (parsed.scheme, parsed.netloc) != self.origin or not parsed.path.startswith(self.base_path):
            return ''
        # Only stable Moodle IDs may be persisted or visited; drop sesskey and other private query values.
        params = parse_qs(parsed.query)
        safe = {key: params[key][0] for key in ('id', 'page', 'section')
                if params.get(key) and params[key][0].isdigit()}
        query = urlencode(safe)
        return parsed._replace(query=query, fragment='').geturl()

    @contextmanager
    def _session(self):
        if self.page is not None:
            yield self.page
            return
        # PLAYWRIGHT_BROWSERS_PATH=0 keeps Chromium with this project's .venv.
        os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '0')
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserUnavailable('Playwright ainda não está instalado.') from None
        expected = app_dir().resolve() / 'browser_profile'
        if self.profile_dir.absolute() != expected or expected.is_symlink():
            raise BrowserUnavailable('Perfil exclusivo de navegador inválido.')
        verify_private_profile()
        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir), headless=False,
                    accept_downloads=False, service_workers='block')
            except Exception:
                # Browser exceptions may contain URLs with private query values.
                raise BrowserUnavailable('Não foi possível abrir o navegador do Campus AI.') from None
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(self.timeout_ms)
                yield page
            finally:
                try:
                    context.close()
                except Exception:
                    # Closing the Chromium window itself may have already
                    # disconnected the browser; this is not a login failure.
                    if not self._closed(page):
                        raise BrowserUnavailable('Falha ao encerrar o navegador do Campus AI.') from None

    def _visit(self, page, url):
        if not self._url(url):
            raise ValueError('Navegação fora do Moodle configurado.')
        page.goto(url, wait_until='domcontentloaded', timeout=self.timeout_ms)
        if not self._url(page.url):
            raise SessionExpired('Navegação saiu do portal Moodle.')
        doc = Document(page.content()).root
        if 'acesso automatizado bloqueado' in doc.text().lower():
            raise PortalBlocked('O portal bloqueou a automação; análise interrompida.')
        return doc

    @staticmethod
    def _authenticated(doc):
        nodes = list(doc.nodes())
        if any(n.tag == 'form' and (n.attrs.get('id') == 'login' or
                any(c.attrs.get('name') == 'password' for c in n.nodes())) for n in nodes):
            return False
        return any(n.has_class('usermenu') or n.attrs.get('id') == 'user-menu-toggle' or
                   (n.tag == 'a' and '/login/logout.php' in n.attrs.get('href', '')) for n in nodes)

    def check_session(self) -> bool:
        with self._session() as page:
            try:
                return self._authenticated(self._visit(page, self.base_url + '/my/'))
            except (PortalBlocked, BrowserUnavailable):
                raise
            except Exception:
                return False

    @staticmethod
    def _closed(page) -> bool:
        """Closing the visible Chromium window is a normal cancellation path."""
        try:
            check = getattr(page, 'is_closed', None)
            return bool(check()) if callable(check) else False
        except Exception:
            return True

    def connect(self, wait_seconds: int = 180, *, cancelled=None) -> bool:
        """Wait for a manual login without blocking Playwright's event dispatch.

        Cancellation and a manually closed window both return False. This does
        not erase the persistent browser profile or inspect course content.
        """
        with self._session() as page:
            # /my/ redirects unauthenticated users to Moodle's login page.
            # An already signed-in user can therefore be recognized immediately.
            page.goto(self.base_url + '/my/', wait_until='domcontentloaded', timeout=self.timeout_ms)
            deadline = time.monotonic() + max(0, wait_seconds)
            while True:
                if (cancelled is not None and cancelled()) or self._closed(page):
                    return False
                try:
                    current = self._url(page.url)
                    if (current and '/login/' not in urlparse(current).path and
                            self._authenticated(Document(page.content()).root)):
                        return True
                except Exception:
                    if self._closed(page) or (cancelled is not None and cancelled()):
                        return False
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                try:
                    # Playwright must be allowed to process navigation and page
                    # close events; time.sleep() starves its synchronous driver.
                    wait = getattr(page, 'wait_for_timeout', None)
                    if callable(wait):
                        wait(min(500, max(1, int(remaining * 1000))))
                    else:
                        # Compatibility with the existing in-memory test pages.
                        time.sleep(min(0.5, remaining))
                except Exception:
                    if self._closed(page) or (cancelled is not None and cancelled()):
                        return False
                    raise

    def open_browser(self):
        with self._session() as page:
            page.goto(self.base_url + '/my/', wait_until='domcontentloaded', timeout=self.timeout_ms)
            page.wait_for_event('close', timeout=0)

    def smoke_local(self) -> bool:
        """Test the exact persistent profile and visible browser without network access."""
        with self._session() as page:
            page.goto('about:blank', wait_until='domcontentloaded', timeout=self.timeout_ms)
            return page.url == 'about:blank'

    def disconnect(self):
        """Remove only the dedicated profile; no other browser profile is touched."""
        expected = app_dir().resolve() / 'browser_profile'
        if self.profile_dir.absolute() != expected or expected.is_symlink():
            raise ValueError('Perfil de navegador inesperado.')
        if expected.exists():
            shutil.rmtree(expected)

    def scan(self, *, cancelled=None, max_courses=None, course_id='') -> BrowserScan:
        if cancelled is not None and cancelled():
            return BrowserScan([], ['Análise interrompida pelo usuário.'], False)
        seen: dict[str, AcademicItem] = {}
        warnings: list[str] = []
        complete = True
        with self._session() as page:
            home = self._visit(page, self.base_url + '/my/')
            if not self._authenticated(home):
                raise SessionExpired('Faça login manualmente pelo navegador do Campus AI.')
            courses = []
            for node in home.nodes():
                if node.tag != 'a':
                    continue
                link = self._url(node.attrs.get('href', ''))
                parsed = urlparse(link)
                ids = parse_qs(parsed.query).get('id', [])
                if parsed.path.endswith('/course/view.php') and ids and ids[0].isdigit():
                    courses.append((ids[0], node.text() or 'Disciplina', link))
            if not courses:
                return BrowserScan([], ['Nenhuma disciplina visível; confirme no AVA.'], False)
            courses = list({course[0]: course for course in courses}.values())
            available_count = len(courses)
            if course_id:
                courses = [course for course in courses if course[0] == course_id]
            if max_courses is not None:
                courses = courses[:max_courses]
            if len(courses) < available_count:
                complete = False
                warnings.append('Leitura piloto limitada a uma disciplina; demais disciplinas não analisadas.')
            if not courses:
                return BrowserScan([], ['Disciplina piloto não encontrada no painel.'], False)
            visited = set()
            for course_id, course_name, course_url in courses:
                if course_url in visited:
                    continue
                try:
                    queue = [course_url]
                    while queue:
                        if cancelled is not None and cancelled():
                            return BrowserScan(list(seen.values()), ['Análise interrompida pelo usuário.'], False)
                        if len(visited) >= self.max_pages:
                            raise RuntimeError('Limite de páginas atingido.')
                        url = queue.pop(0)
                        if url in visited:
                            continue
                        if visited:
                            time.sleep(self.delay_seconds)
                        doc = self._visit(page, url)
                        if not self._authenticated(doc):
                            raise SessionExpired()
                        if not any(n.has_class('section') or n.attrs.get('data-sectionid') for n in doc.nodes()):
                            raise ValueError('Estrutura de seções não reconhecida.')
                        visited.add(url)
                        for node in doc.nodes():
                            if node.tag == 'a' and node.attrs.get('rel') == 'next':
                                next_url = self._url(node.attrs.get('href', ''))
                                next_parsed = urlparse(next_url)
                                if (next_url and next_url not in visited and
                                        next_parsed.path.endswith('/course/view.php') and
                                        parse_qs(next_parsed.query).get('id') == [course_id]):
                                    queue.append(next_url)
                        self._read_course(doc, course_id, course_name, seen)
                except PortalBlocked:
                    raise
                except SessionExpired:
                    warnings.append('Sessão Moodle expirou durante a análise; entre novamente.')
                    return BrowserScan(list(seen.values()), warnings, False)
                except Exception as exc:
                    complete = False
                    warnings.append(f'{course_name}: leitura parcial ({exc.__class__.__name__}); confira no AVA.')
        return BrowserScan(list(seen.values()), warnings, complete)

    def _read_course(self, doc, course_id, course_name, seen):
        for node in doc.nodes():
            if node.tag not in ('div', 'li', 'article') or not (
                    node.has_class('activity') or node.has_class('activity-item')):
                continue
            link_node = next((n for n in node.nodes() if n.tag == 'a' and '/mod/' in n.attrs.get('href', '')), None)
            if link_node is None:
                continue
            link = self._url(link_node.attrs.get('href', ''))
            parsed = urlparse(link)
            ids = parse_qs(parsed.query).get('id', [])
            module_id = node.attrs.get('data-cmid') or (ids[0] if ids else '')
            if not link or not module_id.isdigit():
                continue
            kind = parsed.path.split('/mod/')[-1].split('/')[0]
            if kind not in ('resource', 'page', 'url', 'folder', 'book', 'assign', 'quiz', 'forum', 'lesson'):
                continue
            category = 'assignment' if kind in ('assign', 'quiz') else 'announcement' if kind == 'forum' else 'material'
            times = [n.attrs.get('datetime', '') for n in node.nodes() if n.tag == 'time']
            date = next((value for value in times if value), '')
            status = 'unknown'
            if category == 'assignment':
                lower = node.text().lower()
                if 'não enviado' in lower or 'not submitted' in lower or 'pendente' in lower:
                    status = 'pending'
                elif 'enviado para avaliação' in lower or 'submitted for grading' in lower:
                    status = 'submitted'
            uid = f'moodle:course:{course_id}:module:{module_id}'
            seen[uid] = AcademicItem(uid, 'moodle', category, link_node.text() or 'Conteúdo',
                                     course_name, node.text()[:12000], link,
                                     due_iso=date if category == 'assignment' else '', status=status,
                                     meta={'courseid': int(course_id), 'moduleid': int(module_id),
                                           'type': kind, 'source_added_iso': date if category == 'material' else ''})
