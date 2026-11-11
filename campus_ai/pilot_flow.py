"""The only navigation the pilot performs: to the one authorized course URL.

The URL is rebuilt from a validated numeric id (AuthorizedCourse), never from
page content. Login is always manual: while the portal (or an external sign-in
provider) shows its login screen this module only polls `page.url`; it never
fills fields, clicks, reads the DOM of a foreign origin, or reloads. Cancelling
or timing out leaves the browser and its persistent profile untouched.
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit

from .pilot import PilotRejected, course_url

NAV_TIMEOUT_MS = 20000
LOGIN_WAIT_S = 180
LOAD_WAIT_S = 30
POLL_MS = 1000
MAX_NAVIGATIONS = 3

_CLOSED = 'Navegador fechado. Clique em Analisar para abri-lo novamente.'
_CANCELLED = 'Análise cancelada. O navegador e a sessão foram preservados.'


def _same_course(url: str, course) -> bool:
    try:
        return course_url(url) == course.url
    except PilotRejected:
        return False


def _is_aedb(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == 'https' and parts.netloc == 'ead.aedb.br'


def _is_login(url: str) -> bool:
    parts = urlsplit(url)
    return _is_aedb(url) and (parts.path.startswith('/ava/login/') or parts.path.startswith('/ava/auth/'))


def _is_foreign_https(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == 'https' and parts.netloc != 'ead.aedb.br'


def _check(page, cancelled) -> None:
    if cancelled and cancelled():
        raise PilotRejected(_CANCELLED)
    try:
        closed = page.is_closed()
    except Exception:
        closed = True
    if closed:
        raise PilotRejected(_CLOSED)


def _goto(page, course) -> None:
    assert course_url(course.url) == course.url  # Fixed, validated target.
    try:
        page.goto(course.url, wait_until='domcontentloaded', timeout=NAV_TIMEOUT_MS)
    except Exception as exc:
        # Never include the exception text: it may carry URLs and private query values.
        try:
            closed = page.is_closed()
        except Exception:
            closed = True
        if closed:
            raise PilotRejected(_CLOSED) from None
        if exc.__class__.__name__ == 'TimeoutError':
            raise PilotRejected(f'Tempo esgotado ao abrir a disciplina ({NAV_TIMEOUT_MS // 1000} s). '
                                'Verifique a rede e a disponibilidade da AEDB. A sessão foi preservada; '
                                'clique em Analisar para tentar de novo.') from None
        # Redirects to a login provider can abort the original navigation;
        # the caller inspects the resulting address.


def reach_course(page, reader, course, *, cancelled=None, progress=None, clock=time.monotonic,
                 login_wait_s=LOGIN_WAIT_S, load_wait_s=LOAD_WAIT_S, poll_ms=POLL_MS,
                 max_navigations=MAX_NAVIGATIONS) -> None:
    """Return once `page` shows the authorized course in a signed-in session.

    `progress` receives 'abrindo', 'login' and 'autenticado' (each once, in order
    of occurrence).
    """
    announced = None

    def announce(state):
        nonlocal announced
        if state != announced and progress:
            progress(state)
        announced = state

    navigations = 0
    login_since = loading_since = None
    announce('abrindo')
    while True:
        _check(page, cancelled)
        url = str(page.url)
        needs_login = False
        if _same_course(url, course):
            data, _ = reader._snapshot(True, cancelled, allow_unauthenticated=True)
            if data.get('authenticated') and not data.get('login'):
                announce('autenticado')
                return
            ready = (data.get('diag') or {}).get('ready')
            # A course page still loading is not a login prompt.
            needs_login = bool(data.get('login')) or ready == 'complete'
        elif _is_login(url) or (navigations >= 1 and _is_foreign_https(url)):
            needs_login = True
        elif navigations < max_navigations:
            navigations += 1
            _goto(page, course)
            continue
        else:
            raise PilotRejected('Não foi possível chegar à disciplina autorizada. Entre manualmente na janela do '
                                'navegador e clique em Analisar novamente. A sessão foi preservada.')
        now = clock()
        if needs_login:
            login_since = now if login_since is None else login_since
            announce('login')
            if now - login_since > login_wait_s:
                raise PilotRejected(f'Login não concluído em {login_wait_s // 60} min. A sessão e o navegador '
                                    'foram preservados; entre na janela e clique em Analisar novamente.')
        else:
            loading_since = now if loading_since is None else loading_since
            if now - loading_since > load_wait_s:
                raise PilotRejected(f'A página da disciplina não terminou de carregar em {load_wait_s} s. '
                                    'A sessão foi preservada; tente analisar novamente.')
        try:
            page.wait_for_timeout(poll_ms)
        except Exception:
            raise PilotRejected(_CLOSED) from None
