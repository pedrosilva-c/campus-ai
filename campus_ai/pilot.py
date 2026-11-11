"""Memory-only reading of one authorized AEDB course page.

This module never navigates (see pilot_flow.py for the single, bounded
navigation to the authorized URL). No filesystem, database, credentials, network client or AI provider.
Only a bounded projection of visible DOM fields leaves the renderer.

Title recognition does not rely on one CSS selector: the fixed DOM program
collects a few bounded candidates from independent Moodle structures (page
header, custom course banners, breadcrumb links to the same course ID, other
main-region headings and the tab title). Python groups compatible texts and
asks for a manual choice when incompatible titles have similar support.
"""
from dataclasses import dataclass, replace
import json
import re
import time
import unicodedata
from urllib.parse import urlsplit, parse_qs, urljoin


class PilotRejected(RuntimeError):
    pass


class PilotLoginRequired(PilotRejected):
    """The page is reachable but the student must sign in manually."""


class PilotStop(PilotRejected):
    """The run must end here: cancelled, browser closed or portal block. Never retried or worked around."""


@dataclass(frozen=True)
class PilotLimits:
    max_elements: int = 3000
    timeout_ms: int = 5000
    total_ms: int = 10000
    expand_ms: int = 30000  # Total budget for the automatic section-expansion phase.
    scroll_ms: int = 20000  # Total budget for the programmatic scrolling that loads late content.

    def __post_init__(self):
        if not (100 <= self.max_elements <= 10000 and 500 <= self.timeout_ms <= self.total_ms <= 30000
                and 0 <= self.expand_ms <= 60000 and 0 <= self.scroll_ms <= 60000):
            raise ValueError('Limites piloto inválidos.')


@dataclass(frozen=True)
class PilotSelection:
    url: str
    title: str
    choices: tuple = ()
    confidence: str = 'fonte única'
    sources: tuple = ()

    @property
    def pending(self) -> bool:
        """The student must pick or type the course name before any reading."""
        return self.confidence in ('ambíguo', 'manual')

    def choose(self, title: str) -> 'PilotSelection':
        """Manual resolution. Ambiguous pages accept only titles found on the page;
        'manual' pages accept a typed name, which is only a label: the identity of
        the page rests on the authorized URL plus the signed-in session."""
        if self.confidence == 'manual':
            name = clean_title(title)[:200]
            if not name:
                raise PilotRejected('Informe o nome da disciplina.')
            return replace(self, title=name, confidence='nome informado')
        if title not in self.choices:
            raise PilotRejected('O título escolhido não pertence às opções encontradas na página.')
        return replace(self, title=title, confidence='escolha manual')

    def accepts(self, other) -> bool:
        if not isinstance(other, PilotSelection) or other.url != self.url:
            return False
        if self.confidence == 'manual':
            return (other.confidence == 'nome informado' and other.choices == self.choices
                    and bool(other.title))
        if other == self:
            return True
        return (other.choices == self.choices and other.title in self.choices and
                other.confidence == 'escolha manual')


@dataclass(frozen=True)
class PilotRow:
    course: str
    kind: str
    title: str
    due: str
    url: str
    section: str = ''
    module_id: str = ''


@dataclass(frozen=True)
class Coverage:
    """What the reading actually examined. 'Complete' never means more than this."""
    sections_total: int
    expanded: int          # opened automatically by this analysis and verified loaded
    already_open: int
    inaccessible: int      # left intact or not verified loaded: the result is partial
    materials: int
    activities: int
    others: int = 0
    empty: int = 0         # examined sections that contain no items
    duplicates: int = 0    # repeated entries removed
    reasons: tuple = ()    # ((section name, reason), ...)
    unknown: int = 0       # academic blocks with neither visible content nor a recognized expander
    candidates: int = 0    # candidate regions seen (cards, wrappers and sections)
    layout: int = 0        # candidates that are not academic sections
    safe_expanders: int = 0
    clicked: int = 0
    activity_elements: int = 0
    orphan_links: int = 0  # module links outside academic sections (e.g. navigation cards)
    nav_missing: int = 0   # links to section pages that are not part of this page (not followed)
    unnamed: int = 0
    scrolls: int = 0
    ignored: tuple = ()    # ((reason, count), ...)


@dataclass(frozen=True)
class PilotResult:
    rows: list[PilotRow]
    state: str
    diagnostic: str
    selection: object = None
    coverage: object = None
    navigation: object = None   # NavReport when the run went through navigation cards
    notes: tuple = ()           # reasons (beyond per-section ones) behind the state


@dataclass(frozen=True)
class TitleResolution:
    title: str
    choices: tuple
    confidence: str
    sources: tuple


MODULES = ('resource', 'assign', 'quiz', 'page', 'url', 'folder', 'book', 'forum', 'lesson',
           'choice', 'feedback', 'glossary', 'wiki', 'workshop', 'scorm', 'h5pactivity', 'lti',
           'data', 'bigbluebuttonbn', 'chat', 'survey', 'imscp')
KIND_LABELS = {
    'Seção': 'Seção', 'resource': 'Arquivo', 'assign': 'Tarefa', 'quiz': 'Questionário',
    'page': 'Página', 'url': 'Link', 'folder': 'Pasta', 'book': 'Livro', 'forum': 'Fórum',
    'lesson': 'Lição', 'choice': 'Escolha', 'feedback': 'Pesquisa', 'glossary': 'Glossário',
    'wiki': 'Wiki', 'workshop': 'Laboratório de avaliação', 'scorm': 'Pacote SCORM',
    'h5pactivity': 'H5P', 'lti': 'Ferramenta externa', 'data': 'Base de dados',
    'bigbluebuttonbn': 'Webconferência', 'chat': 'Chat', 'survey': 'Questionário de avaliação',
    'imscp': 'Pacote de conteúdo',
}


MATERIAL_KINDS = frozenset(('resource', 'page', 'url', 'folder', 'book', 'imscp'))
ACTIVITY_KINDS = frozenset(MODULES) - MATERIAL_KINDS
MAX_EXPAND_SECTIONS = 40
MAX_SCROLL_STEPS = 30
SCROLL_WAIT_MS = 400
SCROLL_STABLE_POLLS = 2
EXPAND_ROUNDS = 3
EXPAND_SECTION_TIMEOUT_S = 6.0
EXPAND_POLL_MS = 250
EXPAND_PAUSE_MS = 250
EXPAND_STABLE_POLLS = 2
EXPAND_REASONS = {
    'ambiguous': 'expansor ambíguo (mais de uma região controlada)',
    'unsafe': 'controle não verificável como expansor seguro',
    'none': 'nenhum controle de expansão encontrado',
    'mudou': 'a página mudou antes do clique',
    'ja_aberta': 'a seção já estava aberta',
    'nao_expandiu': 'o clique não expandiu a seção',
    'timeout': 'o conteúdo não terminou de carregar a tempo',
    'tempo': 'tempo limite da expansão atingido',
    'limite': 'limite de seções expandidas por análise atingido',
    'recolhida': 'continuou recolhida (expansão automática não executada ou sem efeito)',
    'desconhecida': 'estado desconhecido: sem conteúdo visível nem expansor reconhecido',
}


def kind_label(kind) -> str:
    return KIND_LABELS.get(str(kind), 'Item')


def course_url(value: str) -> str:
    try:
        p = urlsplit(value)
        q = parse_qs(p.query, keep_blank_values=True)
        valid = (p.scheme == 'https' and p.netloc == 'ead.aedb.br' and
                 p.path == '/ava/course/view.php' and
                 set(q) <= {'id', 'section', 'page', 'sesskey'} and
                 all(len(v) == 1 for v in q.values()) and
                 re.fullmatch(r'[1-9][0-9]*', q.get('id', [''])[0]) and
                 all(re.fullmatch(r'[0-9]+', q[k][0]) for k in ('section', 'page') if k in q))
        if valid:
            return 'https://ead.aedb.br/ava/course/view.php?id=' + q['id'][0]
    except (ValueError, TypeError):
        pass
    raise PilotRejected('Selecione uma página de disciplina em https://ead.aedb.br/ava/.')


def reference_url(value: str) -> str:
    try:
        p = urlsplit(urljoin('https://ead.aedb.br/ava/', value))
        q = parse_qs(p.query)
        if (p.scheme == 'https' and p.netloc == 'ead.aedb.br' and
                re.fullmatch(r'/ava/mod/(' + '|'.join(MODULES) + r')/view\.php', p.path) and
                len(q.get('id', [])) == 1 and re.fullmatch(r'[0-9]+', q['id'][0])):
            return 'https://ead.aedb.br' + p.path + '?id=' + q['id'][0]
    except (ValueError, TypeError):
        pass
    return ''


# --- Title recognition ------------------------------------------------------

SOURCE_WEIGHTS = {'header_h1': 3, 'course_banner': 3, 'breadcrumb': 3, 'h1': 2, 'doc_title': 2}
SOURCE_LABELS = {'header_h1': 'cabeçalho da página', 'course_banner': 'área destacada do curso',
                 'breadcrumb': 'trilha de navegação', 'h1': 'título principal',
                 'doc_title': 'título da aba'}
_PREFIX = re.compile(r'^(?:curso|course|disciplina)\s*[:：]\s*', re.IGNORECASE)
MAX_CHOICES = 5


def clean_title(value) -> str:
    text = unicodedata.normalize('NFC', str(value or ''))
    text = re.sub(r'\s+', ' ', text).strip()[:800]
    # Some themes render a visual copy plus a screen-reader copy of the same
    # title; innerText may join them with or without a space.
    for sep in (' ', ''):
        half = (len(text) - len(sep)) // 2
        if half >= 4 and len(text) == 2 * half + len(sep) and text[:half] == text[half + len(sep):] \
                and text[half:half + len(sep)] == sep:
            text = text[:half]
            break
    return _PREFIX.sub('', text[:400]).strip()


def title_key(value) -> str:
    text = unicodedata.normalize('NFKC', clean_title(value)).casefold()
    text = re.sub(r'\s*[‐-―-]+\s*', ' - ', text)
    return re.sub(r'\s+', ' ', text).strip(' .:;|')


def tab_course_title(value) -> str:
    """Course part of Moodle's tab title. ' | ' separates the site name;
    ' - ' is kept because it often occurs inside AEDB course names."""
    return clean_title(clean_title(value).split(' | ')[0])


def _compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 6 and f' {short} ' in f' {long_} '


def resolve_title(candidates, doc_title='') -> TitleResolution | None:
    groups = {}
    entries = [(c.get('source'), c.get('text')) for c in list(candidates or [])[:40] if isinstance(c, dict)]
    entries.append(('doc_title', tab_course_title(doc_title)))
    for source, raw in entries:
        weight = SOURCE_WEIGHTS.get(source)
        title = clean_title(raw)
        key = title_key(title)
        if not weight or len(key) < 2:
            continue
        group = groups.setdefault(key, {'title': title, 'weight': 0, 'sources': set()})
        if weight > group['weight']:
            group['title'], group['weight'] = title, weight
        group['sources'].add(source)
    if not groups:
        return None
    score = lambda g: sum(SOURCE_WEIGHTS[s] for s in g['sources'])
    pending = sorted(groups.items(), key=lambda kv: (score(kv[1]), len(kv[1]['title'])), reverse=True)
    clusters = []
    while pending:
        (seed_key, seed), rest = pending[0], pending[1:]
        members = [kv for kv in rest if _compatible(seed_key, kv[0])]
        sources = set(seed['sources']).union(*(g['sources'] for _, g in members))
        # Compatible texts contain each other; show the most complete one.
        title = max([seed['title']] + [g['title'] for _, g in members], key=len)
        clusters.append((sum(SOURCE_WEIGHTS[s] for s in sources), title, sources))
        pending = [kv for kv in rest if kv not in members]
    clusters.sort(key=lambda cl: cl[0], reverse=True)
    top_score, title, sources = clusters[0]
    close = [cl for cl in clusters if cl[0] >= top_score - 1]
    labels = tuple(SOURCE_LABELS[s] for s in SOURCE_WEIGHTS if s in sources)
    if len(close) > 1:
        return TitleResolution(title, tuple(cl[1] for cl in close[:MAX_CHOICES]), 'ambíguo', labels)
    return TitleResolution(title, (), 'confirmado' if len(sources) > 1 else 'fonte única', labels)


def _corroborated(data, course_id) -> bool:
    """The page itself (not the address) names the expected course id."""
    ids = data.get('ids') if isinstance(data.get('ids'), dict) else {}
    return any(str(ids.get(k) or '') == str(course_id) for k in ('body', 'cfg'))


def _count(diag, key):
    value = diag.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value < 100000:
        return 0
    return int(value)


def structure_diagnostic(data) -> str:
    """Counts and booleans only: never page text, URLs or attributes."""
    diag = data.get('diag') if isinstance(data.get('diag'), dict) else {}
    ready = diag.get('ready') if diag.get('ready') in ('loading', 'interactive', 'complete') else 'desconhecido'
    return (f'Diagnóstico estrutural: h1 visíveis {_count(diag, "h1_visible")}/{_count(diag, "h1_total")}, '
            f'área de curso {_count(diag, "banner")}, trilha {_count(diag, "breadcrumb")}, '
            f'título da aba {"presente" if data.get("doc_title") else "ausente"}, '
            f'região principal {"sim" if diag.get("main") else "não"}, documento {ready}.')


# Fixed programs, never constructed from academic content. They inspect only the
# current document. SNAPSHOT_JS is read-only. EXPAND_JS may (a) scroll the page and (b) activate
# exactly one kind of control, a verified section expander, only through its 'click' mode.
_COMMON_JS = r'''
 const rendered = e => {
   if (!e || e.closest('[hidden]')) return false;
   const s = getComputedStyle(e);
   return s.visibility !== 'hidden' && s.display !== 'none' && e.getClientRects().length > 0;
 };
 const visible = e => rendered(e) && !e.closest('[aria-hidden="true"]') && getComputedStyle(e).opacity !== '0';
 const pick = (selector, limit) => Array.from(document.querySelectorAll(selector)).slice(0, limit);
 const courseId = (location.search.match(/[?&]id=(\d+)/) || [])[1] || '';
 const body = document.body;
 // Session: the URL is never treated as proof of authentication.
 const notLogged = !!body && body.classList.contains('notloggedin');
 const guest = !!document.querySelector('.usermenu .login, .usermenu a[href*="/login/index.php"]');
 out.authenticated = !notLogged && !guest &&
   !!document.querySelector('.usermenu, #user-menu-toggle, a[href*="/login/logout.php"]');
 out.login = pick('input[type="password"], form#login', 5).some(rendered);
 out.blocked = pick('[role="alert"], .alert, .errorbox, h1', 30).some(e => visible(e) &&
   /acesso automatizado bloqueado|automated access.{0,20}(blocked|denied)|captcha|automação.{0,20}(bloqueada|proibida)/i
     .test(String(e.innerText || '').slice(0, 400)));
 const bodyId = String(body ? body.className : '').match(/(?:^|\s)course-(\d+)(?:\s|$)/);
 out.ids.body = bodyId ? bodyId[1] : '';
 try {
   const cfg = window.M && window.M.cfg && window.M.cfg.courseId;
   out.ids.cfg = cfg ? String(cfg).replace(/\D/g, '').slice(0, 12) : '';
 } catch (_) {}
 const main = document.querySelector('#region-main, [role="main"], #page-content, main');
 const root = main || body;
 const skip = '.drawer, [data-region="drawer"], #courseindex, .courseindex, .block, aside, .navbar, nav, ' +
   '.dropdown-menu, footer, .modal, [role="dialog"]';
 const hiddenCopy = '.accesshide, .sr-only, .visually-hidden';
 const activitySelector = '.activity, .activity-item, [data-for="cmitem"], li[id^="module-"], [class*="modtype_"]';
 const menuLike = '.dropdown-menu, .action-menu, [data-region="action-menu"], .section-actions, [role="menu"], [aria-haspopup]';
 const MODULE_HREF = /\/mod\/(resource|assign|quiz|page|url|folder|book|forum|lesson|choice|feedback|glossary|wiki|workshop|scorm|h5pactivity|lti|data|bigbluebuttonbn|chat|survey|imscp)\/view\.php/;
 // A Moodle academic section carries a strong signature. A bare ".section" is also used by theme cards
 // and layout wrappers, so it only counts when it holds real activity elements.
 const STRONG = 'li.section, [data-for="section"], .course-section, li[id^="section-"], div[id^="section-"], section[id^="section-"]';
 const WEAK = '.section, [data-sectionid], section';
 const BLOCK_TAG = /^(LI|DIV|SECTION|ARTICLE)$/;
 const SECTION_MAX = Math.min(Number(options.max_sections) || 60, 100);
 const plain = e => {
   let value = ''; let guard = 0; const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT); let n;
   while ((n = w.nextNode()) && value.length < 400 && ++guard < 400) {
     const p = n.parentElement;
     if (p && visible(p) && !p.closest(hiddenCopy)) value += ' ' + n.textContent.slice(0, 400 - value.length);
   }
   return value.replace(/\s+/g, ' ').trim().slice(0, 200);
 };
 const topActivities = s => Array.from(s.querySelectorAll(activitySelector)).slice(0, 2000)
   .filter(a => !a.parentElement.closest(activitySelector));
 const modLinks = s => Array.from(s.querySelectorAll('a[href]')).slice(0, 800)
   .filter(a => MODULE_HREF.test(a.getAttribute('href') || '') && !a.closest(menuLike) && !a.closest(activitySelector));
 // ---- Candidate regions -> academic sections (innermost academic blocks only).
 const candidateEls = () => Array.from(root.querySelectorAll(WEAK + ', ' + STRONG)).slice(0, 600)
   .filter(s => BLOCK_TAG.test(s.tagName) && !s.closest(skip) && !s.closest(activitySelector) && !s.closest(menuLike));
 const academicEls = cands => {
   const acad = cands.filter(s => s.matches(STRONG) || topActivities(s).length > 0);
   return acad.filter(s => !acad.some(o => o !== s && s.contains(o)));
 };
 const cands = candidateEls();
 const acadAll = academicEls(cands);
 const acad = acadAll.slice(0, SECTION_MAX);
 const nameOf = s => {
   for (const h of Array.from(s.querySelectorAll('.sectionname, h2, h3, h4')).slice(0, 12)) {
     if (h.closest(activitySelector)) continue;
     const t = plain(h); if (t) return t;
   }
   return String(s.getAttribute('aria-label') || s.getAttribute('data-sectionname') || '')
     .replace(/\s+/g, ' ').trim().slice(0, 200);
 };
 const numberOf = s => {
   const m = String(s.id || '').match(/^section-(\d+)$/);
   if (m) return m[1];
   const n = s.getAttribute('data-number') || s.getAttribute('data-sectionnum');
   return n && /^\d+$/.test(n) ? n : '';
 };
 const sectionKey = (s, i) => i + ':' + String(s.id || s.getAttribute('data-sectionid') || '')
   .replace(/[^A-Za-z0-9_-]/g, '').slice(0, 40);
 // Regions that hide a section's content: targets of aria-controls inside the section, collapse
 // containers and closed <details>. Collapsed = one of them is not shown, or the section's own
 // activities exist in the DOM without being rendered (for a reason other than [hidden] on them).
 const regionsOf = s => {
   const regions = new Set();
   s.querySelectorAll('[aria-controls]').forEach(c => {
     if (c.closest(activitySelector) || c.closest(menuLike)) return;
     String(c.getAttribute('aria-controls')).split(/\s+/).forEach(id => {
       const t = id && document.getElementById(id);
       if (t && s.contains(t) && !t.contains(c) && !t.closest(activitySelector)) regions.add(t);
     });
   });
   s.querySelectorAll('.collapse, .collapsing, details').forEach(t => {
     if (!t.closest(activitySelector) && !t.closest(menuLike)) regions.add(t);
   });
   return Array.from(regions);
 };
 const shown = t => t.tagName === 'DETAILS' ? t.open : rendered(t);
 const stateOf = s => {
   const regions = regionsOf(s);
   const busy = regions.some(t => t.classList.contains('collapsing') || t.getAttribute('aria-busy') === 'true') ||
     !!Array.from(s.querySelectorAll('.loading-icon, .spinner-border, [aria-busy="true"]')).slice(0, 20)
       .find(t => !t.closest(activitySelector) && rendered(t));
   const hiddenRegions = regions.filter(t => !t.classList.contains('collapsing') && !shown(t)).length;
   const hiddenActs = topActivities(s).filter(a => !a.hasAttribute('hidden') &&
     a.getAttribute('aria-hidden') !== 'true' && !rendered(a)).length;
   return {collapsed: hiddenRegions > 0 || hiddenActs > 0, busy, hidden: hiddenRegions + hiddenActs};
 };
 // 'open' needs positive evidence: rendered activities or an expanded, shown region. A block with
 // neither is 'unknown' - never assumed open.
 const blockState = s => {
   const st = stateOf(s);
   const items = topActivities(s).filter(rendered).length +
     (s.matches(STRONG) ? modLinks(s).filter(rendered).length : 0);
   if (st.collapsed) return {state: 'collapsed', busy: st.busy, items, hidden: st.hidden};
   if (items > 0) return {state: 'open', busy: st.busy, items, hidden: 0};
   const expanded = Array.from(s.querySelectorAll('[aria-expanded="true"][aria-controls]')).slice(0, 20).some(c => {
     if (c.closest(activitySelector) || c.closest(menuLike)) return false;
     const t = document.getElementById(String(c.getAttribute('aria-controls')).trim());
     return !!t && s.contains(t) && rendered(t);
   }) || Array.from(s.querySelectorAll('details[open]')).some(d => !d.closest(activitySelector));
   return {state: expanded ? 'open' : 'unknown', busy: st.busy, items, hidden: 0};
 };
 // ---- Expander verification: a control is only used when its real function is a collapse
 // toggle of a region of this same section. Anything else is left alone.
 const BLOCK = /\b(excluir|apagar|remover|delete|remove|enviar|submit|baixar|download|salvar|save|editar|edit|concluir|marcar)\b/i;
 const targetId = c => {
   const ctl = String(c.getAttribute('aria-controls') || '').trim();
   if (ctl && !/\s/.test(ctl)) return ctl;
   const raw = c.getAttribute('data-bs-target') || c.getAttribute('data-target') ||
     (c.tagName === 'A' ? c.getAttribute('href') : '') || '';
   const m = String(raw).match(/^#([A-Za-z][\w:.-]*)$/);
   return m ? m[1] : '';
 };
 const validate = (s, c) => {
   const tag = c.tagName;
   if (tag === 'SUMMARY') {
     const d = c.parentElement;
     if (!d || d.tagName !== 'DETAILS' || d.open || !s.contains(d) || d.closest(activitySelector) ||
         d.closest(menuLike) || d.closest('form') || !rendered(c)) return null;
     if (BLOCK.test(String(c.getAttribute('aria-label') || plain(c)).slice(0, 120))) return null;
     return {control: c, id: 'details:' + Array.from(s.querySelectorAll('details')).indexOf(d)};
   }
   if (!(tag === 'BUTTON' || tag === 'A' || c.getAttribute('role') === 'button')) return null;
   if (tag === 'BUTTON' && (c.disabled || !['', 'button'].includes(String(c.getAttribute('type') || '').toLowerCase()))) return null;
   if (c.closest('form') || c.hasAttribute('download') || c.getAttribute('target') ||
       c.hasAttribute('data-action') || c.getAttribute('aria-disabled') === 'true') return null;
   const kind = String(c.getAttribute('data-toggle') || c.getAttribute('data-bs-toggle') || '').toLowerCase();
   if (kind && kind !== 'collapse') return null;
   if (tag === 'A') { const href = c.getAttribute('href'); if (href !== null && !/^#[\w:.-]*$/.test(href)) return null; }
   if (!rendered(c)) return null;
   const label = String(c.getAttribute('aria-label') || c.getAttribute('title') || plain(c)).slice(0, 120);
   if (BLOCK.test(label)) return null;
   const id = targetId(c); if (!id) return null;
   const t = document.getElementById(id);
   if (!t || t === s || !s.contains(t) || t.contains(c) || t.closest(activitySelector) || rendered(t)) return null;
   return {control: c, id};
 };
 // Structure only (tag, class tokens, attribute presence); never text, hrefs or ids' values.
 const hintOf = s => Array.from(s.querySelectorAll(
     'button, a, summary, [role="button"], [aria-expanded], [tabindex], [data-toggle], [data-bs-toggle], [onclick]'))
   .filter(c => !c.closest(activitySelector) && !c.closest(skip)).slice(0, 4).map(c => {
     const cls = String(c.className && c.className.baseVal === undefined ? c.className : '').split(/\s+/)
       .filter(Boolean).slice(0, 2).map(x => x.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 20)).join('.');
     return c.tagName.toLowerCase() + (cls ? '.' + cls : '') +
       (c.getAttribute('role') ? '[role=' + String(c.getAttribute('role')).replace(/[^a-z]/g, '').slice(0, 12) + ']' : '') +
       (c.hasAttribute('aria-expanded') ? '[aria-expanded=' + (c.getAttribute('aria-expanded') === 'true' ? 'true' : 'false') + ']' : '') +
       (c.hasAttribute('aria-controls') ? '[aria-controls]' : '') + (c.hasAttribute('tabindex') ? '[tabindex]' : '') +
       (c.hasAttribute('onclick') ? '[onclick]' : '') + (c.closest('form') ? '[form]' : '') +
       (c.hasAttribute('download') ? '[download]' : '');
   }).join(', ');
 const classify = s => {
   const pool = Array.from(s.querySelectorAll(
       '[aria-expanded="false"][aria-controls], [data-toggle="collapse"], [data-bs-toggle="collapse"], details:not([open]) > summary'))
     .slice(0, 20).filter(c => !c.closest(activitySelector) && !c.closest(menuLike) && !c.matches(menuLike));
   if (!pool.length) return {status: 'none', controls: 0, hint: hintOf(s)};
   const valid = new Map();
   pool.forEach(c => { const v = validate(s, c); if (v && !valid.has(v.id)) valid.set(v.id, v); });
   if (valid.size > 1) return {status: 'ambiguous', controls: pool.length, hint: hintOf(s)};
   if (valid.size === 0) return {status: 'unsafe', controls: pool.length, hint: hintOf(s)};
   return {status: 'safe', controls: pool.length, control: valid.values().next().value.control};
 };
 // ---- Counts that let the reader explain what it did NOT examine (no text, no URLs).
 const structureInfo = () => {
   const inAcad = el => acadAll.some(s => s.contains(el));
   const acts = Array.from(root.querySelectorAll(activitySelector)).slice(0, 3000)
     .filter(a => !a.closest(skip) && !a.parentElement.closest(activitySelector));
   const links = Array.from(root.querySelectorAll('a[href]')).slice(0, 3000)
     .filter(a => !a.closest(skip) && !a.closest(activitySelector));
   const known = new Set(acadAll.map(numberOf).filter(Boolean));
   // A link to another PAGE of a section (view.php?...&section=N) means that section's content may only be
   // there: it counts when N is not on this page, or is here but shows nothing ('unknown').
   const stateByNumber = new Map(acadAll.map(s => [numberOf(s), blockState(s).state]));
   const missing = new Set(); let navTotal = 0;
   links.forEach(a => {
     const h = String(a.getAttribute('href') || '');
     let m = h.match(/course\/view\.php\?(?:[^#]*&)?id=(\d+)/);
     const sec = h.match(/[?&]section=(\d+)/);
     let n = '', page = false;
     if (m && sec && m[1] === courseId) { n = sec[1]; page = true; }
     else if (/^#section-\d+$/.test(h)) n = h.slice(9);
     if (!n) return;
     navTotal++;
     if (!known.has(n) || (page && stateByNumber.get(n) === 'unknown')) missing.add(n);
   });
   const idx = document.querySelector('#courseindex, .courseindex, [data-region="courseindex"]');
   return {candidates: cands.length, academic: acadAll.length, layout: Math.max(cands.length - acadAll.length, 0),
     activity_elements: acts.length, orphan_activities: acts.filter(a => !inAcad(a)).length,
     orphan_links: links.filter(a => MODULE_HREF.test(a.getAttribute('href') || '') && !a.closest(menuLike) && !inAcad(a)).length,
     nav_total: navTotal, nav_missing: missing.size,
     index: {present: !!idx, sections: idx ? idx.querySelectorAll('[data-for="section"]').length : 0,
             cms: idx ? idx.querySelectorAll('[data-for="cm"]').length : 0},
     unnamed: acad.filter(s => !nameOf(s)).length};
 };
 const describe = (s, i) => {
   const st = blockState(s);
   const info = {key: sectionKey(s, i), name: nameOf(s), number: numberOf(s), state: st.state, busy: st.busy,
                 items: st.items};
   if (st.state !== 'open') {
     const c = classify(s);
     info.expander = {status: c.status, controls: c.controls, hint: c.hint || ''};
   }
   return info;
 };
'''

_TITLE_JS = r'''
 const firstLine = e => (String(e.innerText || '').split('\n').map(s => s.replace(/\s+/g, ' ').trim())
   .find(Boolean) || '').slice(0, 400);
 // Title candidates: bounded, from independent structures, outside menus and drawers.
 const chrome = '.drawer, [data-region="drawer"], #courseindex, .courseindex, .block, aside, .navbar, nav, ' +
   '.dropdown-menu, footer, #page-footer, .modal, [role="dialog"], [role="menu"]';
 const content = '.section, [data-for="section"], .activity, [data-for="cmitem"]';
 const header = '#page-header, .page-header-headings, .page-context-header, [data-region="header"], header';
 const banner = '[class*="course-title"], [class*="coursetitle"], [class*="course-name"], [class*="coursename"], ' +
   '[class*="course-header"] :is(h1, h2, h3), [class*="course-banner"] :is(h1, h2, h3), ' +
   '[class*="coursebanner"] :is(h1, h2, h3), [class*="page-title"], .headermain, ' +
   '[data-region="course-header"] :is(h1, h2, h3)';
 const seen = new Set();
 const add = (source, e) => {
   if (out.title_candidates.length >= 40 || seen.has(e) || !rendered(e)) return;
   seen.add(e);
   const value = firstLine(e) || String(e.getAttribute('aria-label') || '').slice(0, 400);
   if (value) out.title_candidates.push({source, text: value});
 };
 const banners = pick(banner, 20).filter(e => !e.closest(chrome) && !e.closest(content));
 banners.forEach(e => add('course_banner', e));
 const h1s = pick('h1', 20);
 h1s.forEach(e => { if (!e.closest(chrome) && !e.closest(content)) add(e.closest(header) ? 'header_h1' : 'h1', e); });
 const crumbs = pick('.breadcrumb a[href*="/course/view.php"], nav[aria-label] ol a[href*="/course/view.php"]', 20)
   .filter(a => { const m = String(a.getAttribute('href') || '').match(/\/course\/view\.php\?(?:[^#]*&)?id=(\d+)/);
                  return courseId && m && m[1] === courseId; });
 crumbs.concat(pick('.breadcrumb [aria-current="page"]', 5)).forEach(e => add('breadcrumb', e));
 out.diag = {ready: document.readyState, h1_total: h1s.length, h1_visible: h1s.filter(rendered).length,
             banner: banners.length, breadcrumb: crumbs.length, main: !!main};
 if (options.selection_only) return out;
'''

_READ_JS = r'''
 const text = e => {
   let value = ''; const w = document.createTreeWalker(e, NodeFilter.SHOW_TEXT);
   let n; while ((n = w.nextNode()) && value.length < 400) {
     if (!budget()) break;
     if (visible(n.parentElement) && !n.parentElement.closest(hiddenCopy))
       value += ' ' + n.textContent.slice(0, 400 - value.length);
   }
   return value.replace(/\s+/g, ' ').trim().slice(0, 400);
 };
 const dueLabel = /^(vencimento|prazo|data (limite|de entrega)|due|fecha( em)?|encerra( em|mento)?|closes?|fecha de entrega)\s*:/i;
 const secIndex = new Map(acad.map((s, i) => [s, i]));
 const secNames = acad.map(nameOf);
 out.sections = acad.map((s, i) => { const d = describe(s, i); if (d.expander) { d.hint = d.expander.hint; delete d.expander; } return d; });
 out.structure = structureInfo();
 const sectionOf = el => acad.findIndex(s => s.contains(el));
 const records = new Map();
 const w = document.createTreeWalker(root || document.documentElement, NodeFilter.SHOW_ELEMENT,
   {acceptNode: n => n.matches(skip) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
 let e;
 while ((e = w.nextNode()) && budget()) {
   if (!visible(e)) continue;
   if (secIndex.has(e)) {
     out.recognized = true;
     const name = secNames[secIndex.get(e)];
     // Unnamed blocks never become generic "Seção N" rows; they are counted in the structure instead.
     if (name) out.rows.push({kind: 'Seção', title: name, section: name, due: '', url: ''});
   }
   if (e.matches(activitySelector) && !records.has(e) && !e.matches('.modtype_label')) {
     const parent = e.parentElement.closest(activitySelector);
     if (!parent) {
       const type = (String(e.className).match(/(?:^|\s)modtype_([a-z0-9]+)/) || [])[1];
       const si = sectionOf(e);
       const row = {kind: type || 'Item', title: '', due: '', url: '', section: si >= 0 ? secNames[si] : ''};
       records.set(e, row); out.rows.push(row);
     }
   }
   const activity = e.closest(activitySelector);
   let record = records.get(activity);
   if (!record && activity) record = records.get(activity.parentElement.closest(activitySelector));
   if (!record) continue;
   if (e.matches('a[href]') && !record.title) {
     const raw = e.getAttribute('href');
     const match = raw.match(MODULE_HREF);
     if (match) { record.title = text(e); record.kind = match[1]; record.url = raw.slice(0, 2000); }
   }
   if (e.matches('.activity-dates div, [data-region="activity-dates"] div, .due, .duedate') && !e.querySelector('div')) {
     const value = text(e);
     if (!record.due && dueLabel.test(value)) record.due = value;
   }
 }
 // Activities without a link (restricted/unavailable) keep their visible name.
 records.forEach((row, el) => {
   if (row.title) return;
   const name = el.querySelector('.activityname, .instancename');
   if (name && visible(name)) row.title = text(name);
 });
 // Strong sections whose markup has no recognized activity wrapper: fall back to visible module links.
 acad.forEach((s, i) => {
   if (!s.matches(STRONG)) return;
   modLinks(s).forEach(a => {
     if (!visible(a)) return;
     const raw = a.getAttribute('href'); const title = text(a);
     if (title) out.rows.push({kind: raw.match(MODULE_HREF)[1], title, due: '', url: raw.slice(0, 2000),
                               section: secNames[i], via: 'link'});
   });
 });
 out.untitled = out.rows.filter(r => !r.title).length;
 if (out.untitled) out.truncated = true;
 out.rows = out.rows.filter(r => r.title);
 return out;
})'''

SNAPSHOT_JS = r'''(options => {
 const out = {url: location.href, doc_title: String(document.title || '').slice(0, 400),
              authenticated: false, login: false, blocked: false, recognized: false, truncated: false,
              title_candidates: [], ids: {body: '', cfg: ''}, diag: {}, rows: [], sections: [], structure: {}};
 const end = performance.now() + options.timeout_ms;
 let count = 0;
 const budget = () => {
   if (++count > options.max_elements || performance.now() > end) {
     out.truncated = true; return false;
   } return true;
 };''' + _COMMON_JS + _TITLE_JS + _READ_JS

# Modes: 'scroll'/'top' move the viewport only; 'plan' lists academic sections (no interaction);
# 'click' activates ONE verified expander of the section named by `key`; 'state' reports whether
# that section finished expanding.
EXPAND_JS = r'''(options => {
 const out = {url: location.href, authenticated: false, login: false, blocked: false,
              ids: {body: '', cfg: ''}, sections: [], truncated_sections: false, structure: {}};''' + _COMMON_JS + r'''
 const scrollers = () => {
   const set = new Set([document.scrollingElement || document.documentElement]);
   pick('#page, #page-content, #region-main, [role="main"], .main-container, main', 6).forEach(e => {
     if (e.scrollHeight > e.clientHeight + 40 && /(auto|scroll)/.test(getComputedStyle(e).overflowY)) set.add(e);
   });
   return Array.from(set);
 };
 if (options.mode === 'top') {
   scrollers().forEach(e => { e.scrollTop = 0; });
   out.y = 0;
   return out;
 }
 if (options.mode === 'scroll') {
   const els = scrollers();
   els.forEach(e => { e.scrollTop = e.scrollTop + Math.max(200, Math.floor(e.clientHeight * 0.85)); });
   try { window.dispatchEvent(new Event('scroll')); } catch (_) {}
   out.height = Math.max(...els.map(e => e.scrollHeight));
   out.bottom = els.every(e => e.scrollTop + e.clientHeight >= e.scrollHeight - 4);
   out.activities = Math.min(root.querySelectorAll(activitySelector).length, 3000);
   out.sections = candidateEls().length;
   return out;
 }
 const find = key => acad.findIndex((s, i) => sectionKey(s, i) === key);
 if (options.mode === 'plan') {
   out.truncated_sections = acadAll.length > SECTION_MAX;
   out.sections = acad.map(describe);
   out.structure = structureInfo();
   return out;
 }
 const index = find(String(options.key || ''));
 if (options.mode === 'state') {
   out.found = index >= 0;
   if (index >= 0) {
     const s = acad[index]; const st = blockState(s);
     out.expanded = st.state !== 'collapsed'; out.busy = st.busy; out.items = st.items;
     out.text_len = Math.min(String(s.innerText || '').length, 100000);
   }
   return out;
 }
 if (options.mode === 'click') {
   out.clicked = false; out.reason = 'mudou';
   if (index < 0) return out;
   const s = acad[index];
   if (blockState(s).state !== 'collapsed') { out.reason = 'ja_aberta'; return out; }
   const c = classify(s);
   if (c.status !== 'safe') { out.reason = c.status; return out; }
   c.control.click();
   out.clicked = true; out.reason = '';
 }
 return out;
})'''


class PilotReader:
    RETRIES = 3
    RETRY_WAIT_MS = 700

    def __init__(self, page, cdp, limits=None):
        self.page, self.cdp = page, cdp
        self.limits = limits or PilotLimits()

    def _check_cancel(self, cancelled):
        if cancelled and cancelled():
            raise PilotStop('Análise cancelada; nenhum resultado aplicado. O navegador e a sessão foram preservados.')

    def _snapshot(self, selection_only, cancelled, started=None, allow_unauthenticated=False):
        options = dict(max_elements=self.limits.max_elements, timeout_ms=self.limits.timeout_ms,
                       selection_only=selection_only, max_sections=MAX_EXPAND_SECTIONS + 20)
        return self._evaluate(SNAPSHOT_JS, options, cancelled, started, allow_unauthenticated)

    def _evaluate(self, program, options, cancelled, started=None, allow_unauthenticated=False):
        if started is None:
            started = time.monotonic()
        self._check_cancel(cancelled)
        try:
            if self.page.is_closed():
                raise PilotStop('Navegador fechado. Clique em Analisar para abri-lo novamente.')
            if str(self.page.url).startswith('https://ead.aedb.br/ava/login/'):
                raise PilotLoginRequired('Sessão expirada. Faça login manual na janela do navegador.')
            expected = course_url(self.page.url)
            response = self.cdp.send('Runtime.evaluate', {
                'expression': program + '(' + json.dumps(options) + ')',
                'returnByValue': True, 'timeout': self.limits.timeout_ms,
            })
            self._check_cancel(cancelled)
            if time.monotonic() - started > self.limits.total_ms / 1000:
                raise PilotRejected('Timeout total do piloto; resultado descartado.')
            if response.get('exceptionDetails'):
                raise PilotRejected('Timeout ou falha na leitura do DOM; resultado descartado.')
            data = response['result']['value']
            if self.page.is_closed():
                raise PilotStop('Navegador fechado. Clique em Analisar para abri-lo novamente.')
            if course_url(self.page.url) != expected or course_url(data['url']) != expected:
                raise PilotRejected('A disciplina mudou durante a leitura. Clique em Analisar novamente.')
            if data.get('blocked'):
                raise PilotStop('Bloqueio do portal identificado. Interrompa o piloto e confirme a política institucional.')
            unauthenticated = bool(data.get('login')) or not data.get('authenticated')
            if unauthenticated and not allow_unauthenticated:
                raise PilotLoginRequired('Sessão não reconhecida ou expirada. Faça login manual.')
            want = expected.rsplit('=', 1)[1]
            ids = data.get('ids') if isinstance(data.get('ids'), dict) else {}
            if any(str(ids.get(k) or '') not in ('', want) for k in ('body', 'cfg')):
                raise PilotRejected('A página carregada indica outra disciplina (ID divergente do endereço). '
                                    'Recarregue manualmente e clique em Analisar novamente.')
            return data, expected
        except PilotRejected:
            raise
        except Exception:
            raise PilotRejected('Falha ou tempo esgotado no navegador. Nenhum conteúdo foi salvo; a sessão foi preservada. '
                                'Tente analisar novamente.') from None

    def select(self, *, cancelled=None):
        started = time.monotonic()
        attempt = 0
        while True:
            data, url = self._snapshot(True, cancelled, started)
            found = resolve_title(data.get('title_candidates'), data.get('doc_title', ''))
            if found:
                return PilotSelection(url, found.title, found.choices, found.confidence, found.sources)
            attempt += 1
            remaining_ms = self.limits.total_ms - (time.monotonic() - started) * 1000
            if attempt >= self.RETRIES or remaining_ms < self.RETRY_WAIT_MS + self.limits.timeout_ms:
                raise PilotRejected('Título da disciplina não reconhecido nesta página. ' + structure_diagnostic(data) +
                                    ' Nenhuma inspeção adicional realizada; aguarde o carregamento e selecione novamente.')
            # Themes may render the course header asynchronously. Wait on the
            # same page; never reload or navigate.
            try:
                self.page.wait_for_timeout(self.RETRY_WAIT_MS)
            except Exception:
                raise PilotStop('Navegador fechado ou indisponível durante a identificação. Selecione novamente.') from None
            self._check_cancel(cancelled)

    def identify(self, course, *, cancelled=None):
        """Identity of the page against an authorized course.

        Automatic when the visible title matches the authorized name, or when the
        page's own course id (body class / M.cfg) equals the authorized id: an
        unrecognized custom header then does not block reading. The URL alone is
        never accepted. Otherwise the student confirms or types the name.
        """
        started = time.monotonic()
        wanted = title_key(course.name)
        attempt = 0
        while True:
            data, url = self._snapshot(True, cancelled, started)
            if url != course.url:
                raise PilotRejected('A página aberta não é a disciplina autorizada. Clique em Analisar novamente.')
            found = resolve_title(data.get('title_candidates'), data.get('doc_title', ''))
            names = ([found.title] + list(found.choices)) if found else []
            match = next((n for n in names if _compatible(wanted, title_key(n))), None)
            if match:
                confidence = found.confidence if found.confidence != 'ambíguo' else 'fonte única'
                return PilotSelection(url, match, (), confidence, found.sources)
            attempt += 1
            remaining_ms = self.limits.total_ms - (time.monotonic() - started) * 1000
            if attempt >= self.RETRIES or remaining_ms < self.RETRY_WAIT_MS + self.limits.timeout_ms:
                break
            # The course header may render asynchronously: wait on this same page.
            try:
                self.page.wait_for_timeout(self.RETRY_WAIT_MS)
            except Exception:
                raise PilotStop('Navegador fechado ou indisponível durante a identificação. '
                                    'Clique em Analisar para abri-lo novamente.') from None
            self._check_cancel(cancelled)
        if _corroborated(data, course.course_id):
            title = found.title if found and found.confidence != 'ambíguo' else course.name
            return PilotSelection(url, title, (), 'id do curso', ('id do curso',))
        suggestions = tuple(dict.fromkeys(names + [course.name]))[:MAX_CHOICES]
        return PilotSelection(url, course.name, suggestions, 'manual', ())

    def _wait(self, ms):
        try:
            self.page.wait_for_timeout(ms)
        except Exception:
            raise PilotStop('Navegador fechado ou indisponível. Clique em Analisar para abri-lo novamente.') from None

    def _expand_options(self, mode, key=None):
        options = dict(mode=mode, max_elements=self.limits.max_elements, timeout_ms=self.limits.timeout_ms,
                       max_sections=MAX_EXPAND_SECTIONS + 20)
        if key is not None:
            options['key'] = key
        return options

    def explore_page(self, *, cancelled=None):
        """Scroll the page top to bottom (bounded) so late-rendered content exists before reading.

        Only the viewport moves: nothing is clicked. The page is returned to the top. Returns
        {'steps': n, 'complete': bool}; incomplete means the step or time limit ended it first.
        """
        started = time.monotonic()
        budget = self.limits.scroll_ms / 1000
        steps, stable, previous, complete = 0, 0, None, False
        while steps < MAX_SCROLL_STEPS and time.monotonic() - started < budget:
            metrics, _url = self._evaluate(EXPAND_JS, self._expand_options('scroll'), cancelled)
            steps += 1
            if metrics.get('height') is None:      # no geometry reported: nothing to scroll
                complete = True
                break
            signature = (metrics.get('height'), metrics.get('activities'), metrics.get('sections'))
            stable = (stable + 1 if signature == previous else 1) if metrics.get('bottom') else 0
            previous = signature
            if metrics.get('bottom') and stable >= SCROLL_STABLE_POLLS:
                complete = True
                break
            self._wait(SCROLL_WAIT_MS)
        self._evaluate(EXPAND_JS, self._expand_options('top'), cancelled)
        return {'steps': steps, 'complete': complete}

    def _await_expanded(self, key, deadline, cancelled):
        """Wait until the clicked section is open, finished loading and stable."""
        previous, stable = None, 0
        while True:
            state, _ = self._evaluate(EXPAND_JS, self._expand_options('state', key), cancelled)
            if state.get('found') is False:
                return 'mudou'
            signature = (state.get('items'), state.get('text_len'))
            opened = bool(state.get('expanded'))
            if opened and not state.get('busy'):
                stable = stable + 1 if signature == previous else 1
                if stable >= EXPAND_STABLE_POLLS:
                    return 'ok'
            else:
                stable = 0
            previous = signature
            if time.monotonic() >= deadline:
                return 'timeout' if opened else 'nao_expandiu'
            self._wait(EXPAND_POLL_MS)

    def expand_sections(self, *, cancelled=None, on_sections=None):
        """Open collapsed sections of this course page, one verified expander at a time.

        Only the fixed EXPAND_JS program interacts with the page, and only through a
        control it re-validates immediately before clicking. Sections whose expander is
        ambiguous, unsafe or missing are left intact and reported. No activity page is
        opened. Returns {'expanded', 'failed', 'hints', 'safe', 'clicks', 'truncated'}.
        """
        started = time.monotonic()
        budget = self.limits.expand_ms / 1000
        attempted, expanded, failed, hints, safe_keys = set(), {}, {}, {}, set()
        clicks, truncated, announced = 0, False, False
        for _ in range(EXPAND_ROUNDS):
            plan, _url = self._evaluate(EXPAND_JS, self._expand_options('plan'), cancelled)
            truncated = truncated or bool(plan.get('truncated_sections'))
            sections = [x for x in (plan.get('sections') or []) if isinstance(x, dict)]
            if on_sections and not announced:
                announced = True
                on_sections([clean_title(x.get('name'))[:60] for x in sections if x.get('name')])
            for sec in sections:
                expander = sec.get('expander') if isinstance(sec.get('expander'), dict) else {}
                if sec.get('state') != 'open' and expander.get('hint'):
                    hints[str(sec.get('key'))] = _safe_hint(expander.get('hint'))
                if sec.get('state') == 'collapsed' and expander.get('status') == 'safe':
                    safe_keys.add(str(sec.get('key')))
            todo = [x for x in sections if x.get('state') == 'collapsed' and str(x.get('key')) not in attempted]
            if not todo:
                break
            for sec in todo:
                key = str(sec.get('key'))
                name = clean_title(sec.get('name'))[:200] or _anonymous(sec)
                attempted.add(key)
                expander = sec.get('expander') if isinstance(sec.get('expander'), dict) else {}
                status = expander.get('status')
                if status != 'safe':
                    reason = EXPAND_REASONS.get(status, EXPAND_REASONS['unsafe'])
                    hint = hints.get(key, '')
                    failed[key] = (name, reason + (f'; estrutura: {hint}' if hint else ''))
                    continue
                if clicks >= MAX_EXPAND_SECTIONS:
                    failed[key] = (name, EXPAND_REASONS['limite']); continue
                if time.monotonic() - started >= budget:
                    failed[key] = (name, EXPAND_REASONS['tempo']); continue
                self._check_cancel(cancelled)
                result, _url = self._evaluate(EXPAND_JS, self._expand_options('click', key), cancelled)
                if not result.get('clicked'):
                    failed[key] = (name, EXPAND_REASONS.get(result.get('reason'), EXPAND_REASONS['mudou'])); continue
                clicks += 1
                deadline = min(time.monotonic() + EXPAND_SECTION_TIMEOUT_S, started + budget)
                outcome = self._await_expanded(key, deadline, cancelled)
                if outcome == 'ok':
                    expanded[key] = name
                elif outcome == 'timeout' and time.monotonic() >= started + budget:
                    failed[key] = (name, EXPAND_REASONS['tempo'])
                else:
                    failed[key] = (name, EXPAND_REASONS.get(outcome, EXPAND_REASONS['mudou']))
                self._wait(EXPAND_PAUSE_MS)
        return {'expanded': expanded, 'failed': failed, 'hints': hints, 'safe': len(safe_keys),
                'clicks': clicks, 'truncated': truncated}

    def read(self, selected, *, cancelled=None, expand=False, progress=None, on_sections=None,
             check_identity=True, check_nav=True):
        if selected.pending:
            raise PilotRejected('Informe ou confirme o nome da disciplina antes de ler.')
        if course_url(self.page.url) != selected.url:
            raise PilotRejected('Página alterada após a identificação. Clique em Analisar novamente.')
        report = explore = None
        if expand:
            # 1) scroll so late content exists, 2) open verified expanders, 3) scroll again if anything opened.
            if progress:
                progress('explorando')
            explore = self.explore_page(cancelled=cancelled)
            if progress:
                progress('expandindo')
            report = self.expand_sections(cancelled=cancelled, on_sections=on_sections)
            if report['clicks']:
                again = self.explore_page(cancelled=cancelled)
                explore = {'steps': explore['steps'] + again['steps'],
                           'complete': explore['complete'] and again['complete']}
        if progress:
            progress('analisando')
        data, url = self._snapshot(False, cancelled)
        if url != selected.url:
            raise PilotRejected('Disciplina alterada; resultado descartado.')
        if not check_identity:
            pass
        elif selected.confidence == 'id do curso':
            if not _corroborated(data, url.rsplit('=', 1)[1]):
                raise PilotRejected('O id da disciplina não foi reconfirmado na página; resultado descartado.')
        elif selected.confidence != 'nome informado':
            keys = [title_key(c.get('text')) for c in (data.get('title_candidates') or []) if isinstance(c, dict)]
            keys.append(title_key(tab_course_title(data.get('doc_title', ''))))
            wanted = title_key(selected.title)
            if not any(k and _compatible(wanted, k) for k in keys):
                raise PilotRejected('Disciplina alterada ou título não confirmado novamente; resultado descartado.')
        rows, counts = _build_rows(data, selected.title, self.limits.max_elements)
        coverage = _build_coverage(data, report, counts, explore)
        state, notes = _decide(coverage, data, report, explore, check_nav)
        return PilotResult(rows, state, coverage_text(coverage, state, notes), coverage=coverage,
                           notes=tuple(notes))


def _plural(n, one, many):
    return f'{n} {one if n == 1 else many}'


def _int(value) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < 10 ** 6 else 0


def _safe_hint(value) -> str:
    """Tag names and attribute presence only; anything else is dropped."""
    return re.sub(r'[^A-Za-z0-9\[\]\-_=., ]', '', str(value or ''))[:140]


def _anonymous(sec) -> str:
    number = re.sub(r'[^0-9]', '', str(sec.get('number') or ''))[:6]
    return f'bloco sem nome (seção {number})' if number else 'bloco sem nome'


def _build_rows(data, course, max_rows):
    seen, rows = set(), []
    counts = dict(materials=0, activities=0, others=0, duplicates=0)
    for r in (data.get('rows') or [])[:max_rows]:
        if not isinstance(r, dict) or not r.get('title'):
            continue
        raw_kind = str(r.get('kind', 'Item'))
        title = str(r['title'])[:400]
        section = clean_title(r.get('section'))[:200]
        url = reference_url(r.get('url', ''))
        module_id = url.rsplit('=', 1)[1] if url else ''
        if raw_kind == 'Seção':
            key = ('secao', title.casefold())
        elif module_id:
            key = ('modulo', raw_kind, module_id)
        else:
            key = ('item', section.casefold(), raw_kind, title.casefold())
        if key in seen:
            counts['duplicates'] += 1
            continue
        seen.add(key)
        if raw_kind != 'Seção':
            bucket = 'materials' if raw_kind in MATERIAL_KINDS else 'activities' if raw_kind in ACTIVITY_KINDS else 'others'
            counts[bucket] += 1
        rows.append(PilotRow(course, kind_label(raw_kind), title, str(r.get('due') or 'Não informado')[:400],
                             url, section, module_id))
    return rows, counts


def _build_coverage(data, report, counts, explore):
    sections = [x for x in (data.get('sections') or []) if isinstance(x, dict)]
    structure = data.get('structure') if isinstance(data.get('structure'), dict) else {}
    failed = report['failed'] if report else {}
    done = report['expanded'] if report else {}
    hints = report['hints'] if report else {}
    n_expanded = n_open = n_empty = n_unknown = n_inaccessible = 0
    reasons = []
    for sec in sections:
        key = str(sec.get('key'))
        name = clean_title(sec.get('name'))[:200] or _anonymous(sec)
        state = sec.get('state')
        if key in failed:
            n_inaccessible += 1
            reasons.append(failed[key])
        elif state == 'collapsed':
            n_inaccessible += 1
            reasons.append((name, EXPAND_REASONS['recolhida']))
        elif state == 'unknown':
            n_unknown += 1
            hint = _safe_hint(sec.get('hint')) or hints.get(key, '')
            reasons.append((name, EXPAND_REASONS['desconhecida'] + (f'; estrutura: {hint}' if hint else '')))
        else:
            if key in done:
                n_expanded += 1
            else:
                n_open += 1
            if not sec.get('items'):
                n_empty += 1
    layout, nav_missing = _int(structure.get('layout')), _int(structure.get('nav_missing'))
    orphan_links, orphan_acts = _int(structure.get('orphan_links')), _int(structure.get('orphan_activities'))
    untitled = _int(data.get('untitled'))
    ignored = tuple((label, n) for label, n in (
        ('layout', layout), ('cartões de navegação para outra página', nav_missing),
        ('links de módulo fora de seções', orphan_links), ('atividades fora de seções', orphan_acts),
        ('itens sem título', untitled), ('repetições', counts['duplicates'])) if n)
    return Coverage(
        len(sections), n_expanded, n_open, n_inaccessible, counts['materials'], counts['activities'],
        counts['others'], n_empty, counts['duplicates'], tuple(reasons), n_unknown,
        _int(structure.get('candidates')), layout, report['safe'] if report else 0,
        report['clicks'] if report else 0, _int(structure.get('activity_elements')), orphan_links, nav_missing,
        _int(structure.get('unnamed')), explore['steps'] if explore else 0, ignored)


def _decide(c, data, report, explore, check_nav=True):
    """completa / parcial / nao_validada, with the reasons that are not already per-section."""
    structure = data.get('structure') if isinstance(data.get('structure'), dict) else {}
    index = structure.get('index') if isinstance(structure.get('index'), dict) else {}
    index_cms = _int(index.get('cms')) if index.get('present') else None
    items = c.materials + c.activities + c.others
    notes = []
    if c.sections_total == 0:
        return 'nao_validada', ['estrutura acadêmica não identificada: nenhuma seção reconhecida']
    verified_empty = (items == 0 and c.inaccessible == 0 and c.unknown == 0 and index_cms == 0
                      and c.orphan_links == 0 and _int(structure.get('orphan_activities')) == 0)
    if items == 0 and c.inaccessible == 0 and not verified_empty:
        return 'nao_validada', ['nenhum material ou atividade extraído e nada confirma que a disciplina esteja vazia']
    if data.get('truncated'):
        notes.append('limite de nós/tempo atingido ou item sem título reconhecido')
    if report and report['truncated']:
        notes.append('há mais seções do que o limite de análise')
    if explore and not explore['complete']:
        notes.append('rolagem incompleta (limite de passos ou de tempo): conteúdo tardio pode não ter carregado')
    if c.nav_missing and check_nav:
        notes.append(f'{_plural(c.nav_missing, "link leva", "links levam")} a outra página de seção; '
                     'seguir links exige autorização específica')
    if index_cms is not None and index_cms > items:
        notes.append(f'o índice do curso lista {index_cms} itens; foram extraídos {items}')
    return ('parcial' if (c.inaccessible or c.unknown or notes) else 'completa'), notes


_LABELS = {'completa': 'Cobertura completa', 'parcial': 'Cobertura parcial', 'nao_validada': 'Cobertura não validada'}


def coverage_text(c, state, notes=(), nav_text=''):
    """Counts only. 'Complete' never means more than the academic sections listed here."""
    parts = [_plural(c.sections_total, 'seção acadêmica reconhecida', 'seções acadêmicas reconhecidas'),
             _plural(c.expanded, 'expandida automaticamente', 'expandidas automaticamente'),
             _plural(c.already_open, 'já aberta', 'já abertas')]
    if c.unknown:
        parts.append(f'{c.unknown} de estado desconhecido')
    parts.append(_plural(c.inaccessible, 'não acessível', 'não acessíveis'))
    text = _LABELS.get(state, 'Cobertura') + ': ' + ', '.join(parts)
    if c.reasons:
        shown = '; '.join(f'{name[:60]}: {why}' for name, why in c.reasons[:5])
        text += f' ({shown}{"; ..." if len(c.reasons) > 5 else ""})'
    items = c.materials + c.activities + c.others
    text += (f'. {_plural(c.materials, "material", "materiais")} e {_plural(c.activities, "atividade", "atividades")} '
             'extraídos')
    if c.others:
        text += f' (+{c.others} de outros tipos)'
    if c.empty:
        text += f'; {_plural(c.empty, "seção sem itens", "seções sem itens")}'
    ignored = ', '.join(f'{label} {n}' for label, n in c.ignored) or 'nenhum'
    text += (f'. Diagnóstico estrutural: regiões candidatas {c.candidates}; expansores seguros {c.safe_expanders}, '
             f'acionados {c.clicked}; elementos de atividade {c.activity_elements}; itens extraídos {items}; '
             f'rolagens {c.scrolls}; ignorados: {ignored}')
    if nav_text:
        text += '. ' + nav_text
    if notes:
        text += '. Motivos: ' + '; '.join(notes)
    return (text + '. Estado de entrega não verificado: nenhuma atividade é classificada como pendente. '
            'Nenhuma atividade foi aberta, enviada ou alterada.')
