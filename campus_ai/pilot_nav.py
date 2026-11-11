"""Controlled navigation through the course's navigation cards.

The AEDB course home is a page of cards; academic content lives behind them. This module finds the
cards, classifies what each one does WITHOUT touching it, and only then moves:

* a link (or a destination written in a data attribute / inline script) is opened BY ADDRESS after the
  address passed `classify_destination`; the card's own handler never runs;
* a same-page tab control is clicked once, after semantic validation;
* a card whose behaviour cannot be verified is not touched unless the student confirms it.

Everything is bounded (depth one, <= MAX_NAV_PAGES pages, time per step, cancellable), blocked labels
(feedback, contact the teacher, submit, delete, ...) are never targeted, no download or submission page
is opened, and the course home is restored afterwards. The page content itself is read with the
existing PilotReader machinery (scrolling, verified section expanders, honest coverage).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import json
import re
import time
import unicodedata
from urllib.parse import parse_qs, urlsplit

from .pilot import (MAX_EXPAND_SECTIONS, PilotLoginRequired, PilotRejected, PilotResult, PilotStop,
                    _COMMON_JS, clean_title, coverage_text)

NAV_TIMEOUT_MS = 20000
SETTLE_S = 15.0
SETTLE_POLL_MS = 400
MAX_NAV_PAGES = 3          # destination, home again, and one spare; depth is always one
MAX_CARDS = 60

# Labels are matched without accents, case or spacing.
TARGET_LABELS = ('atividades avaliativas',)
STUDY_LABELS = ('trilhas de aprendizagem',)
INFO_LABELS = ('informacoes da disciplina', 'avisos', 'curriculo lattes')
BLOCKED_WORDS = ('feedback', 'fale com', 'enviar', 'finalizar', 'concluir', 'responder', 'excluir', 'editar',
                 'baixar', 'download', 'submeter', 'marcar como', 'tentativa')
DISPLAY = {'atividades avaliativas': 'Atividades Avaliativas', 'trilhas de aprendizagem': 'Trilhas de Aprendizagem'}
LISTS = {'target': list(TARGET_LABELS), 'study': list(STUDY_LABELS), 'info': list(INFO_LABELS),
         'blocked': list(BLOCKED_WORDS)}


def normalize_label(text) -> str:
    decomposed = unicodedata.normalize('NFD', str(text or ''))
    stripped = ''.join(ch for ch in decomposed if unicodedata.category(ch) != 'Mn')
    return re.sub(r'\s+', ' ', stripped).strip().lower()


def role_of(label) -> str:
    """target / study / info / blocked / other. A blocked word anywhere in the label always wins."""
    n = normalize_label(label)
    if not n:
        return 'other'
    if any(word in n for word in BLOCKED_WORDS):
        return 'blocked'
    for role, names in (('target', TARGET_LABELS), ('study', STUDY_LABELS), ('info', INFO_LABELS)):
        if n in names:
            return role
    return 'other'


# --- Destination validation (Python decides; the page's own opinion is never trusted) -------------

_DENY = re.compile(
    r'^/ava/(mod/(assign|quiz|forum|lesson|workshop|choice|feedback|survey|chat|data|glossary|wiki|lti|scorm|'
    r'h5pactivity|bigbluebuttonbn|resource|url|imscp)/|pluginfile\.php|login/|message/|user/|admin/|'
    r'course/(delete|edit|modedit|management|bulkcompletion))')
_READABLE_MODULE = re.compile(r'^/ava/mod/(page|book|folder)/view\.php$')


@dataclass(frozen=True)
class Destination:
    kind: str          # course | unsupported | unknown | blocked
    url: str = ''
    route: str = ''
    reason: str = ''


def route_pattern(url: str) -> str:
    """Path with numbers hidden and only query KEY names: never identifiers or values."""
    try:
        parts = urlsplit(url)
        keys = sorted(set(parse_qs(parts.query, keep_blank_values=True)))
        return re.sub(r'[0-9]+', 'N', parts.path) + ('?' + '&'.join(keys) if keys else '')
    except ValueError:
        return ''


def classify_destination(url, course_id) -> Destination:
    try:
        parts = urlsplit(str(url))
        host, port = parts.hostname, parts.port
    except ValueError:
        return Destination('blocked', reason='endereço inválido')
    if parts.scheme != 'https' or host != 'ead.aedb.br' or port is not None or parts.username or parts.password:
        return Destination('blocked', route=route_pattern(url), reason='fora da AEDB ou esquema inseguro')
    route = route_pattern(url)
    if _DENY.match(parts.path):
        return Destination('blocked', route=route, reason='rota de atividade, arquivo ou conta')
    if parts.path == '/ava/course/view.php':
        query = parse_qs(parts.query, keep_blank_values=True)
        if (set(query) <= {'id', 'section'} and all(len(v) == 1 for v in query.values())
                and re.fullmatch(r'[1-9][0-9]{0,9}', query.get('id', [''])[0])
                and re.fullmatch(r'[0-9]{1,6}', query.get('section', ['0'])[0])):
            if query['id'][0] != str(course_id):
                return Destination('blocked', route=route, reason='outra disciplina')
            canonical = 'https://ead.aedb.br/ava/course/view.php?id=' + query['id'][0]
            if 'section' in query:
                canonical += '&section=' + query['section'][0]
            return Destination('course', canonical, route)
        return Destination('blocked', route=route, reason='parâmetros não permitidos')
    if _READABLE_MODULE.match(parts.path):
        return Destination('unsupported', route=route, reason='página de módulo')
    return Destination('unknown', route=route, reason='rota desconhecida')


# --- The page-side program --------------------------------------------------------------------

# Modes: 'cards' (describe, never touch), 'probe' (is the page settled?), 'tab_click' and 'card_click'
# (one validated click on the card named by `key`, only if its label still matches `label`).
NAV_JS = r'''(options => {
 const out = {url: location.href, authenticated: false, login: false, blocked: false,
              ids: {body: '', cfg: ''}, cards: [], structure: {}, diag: {}};''' + _COMMON_JS + r'''
 const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
   .replace(/\s+/g, ' ').trim();
 const lists = options.lists || {};
 const roleOf = label => {
   const n = norm(label); if (!n) return 'other';
   if ((lists.blocked || []).some(w => n.includes(w))) return 'blocked';
   for (const r of ['target', 'study', 'info']) if ((lists[r] || []).includes(n)) return r;
   return 'other';
 };
 if (options.mode === 'probe') {
   out.diag = {ready: document.readyState};
   out.academic = acadAll.length;
   out.activities = Math.min(root.querySelectorAll(activitySelector).length, 3000);
   return out;
 }
 const CLICK = 'a[href], button, [role="button"], [role="link"], [role="tab"], [onclick], [data-href], [data-url], [data-link]';
 const BOX = '.card, [class*="card"], [class*="cartao"], [class*="tile"], article, li';
 const inScope = e => !e.closest(skip) && !e.closest(menuLike) && !e.closest(activitySelector) &&
   !acadAll.some(s => s.contains(e));
 const parse = raw => { try { return new URL(raw, location.href); } catch (_) { return null; } };
 const destOf = c => {
   if (c.tagName === 'A' && c.hasAttribute('href')) {
     const href = String(c.getAttribute('href') || '').trim();
     if (!href || /^javascript:/i.test(href)) return {kind: 'js', dest: ''};
     if (href.charAt(0) === '#') return {kind: 'fragment', dest: ''};
     return {kind: 'link', dest: c.href};
   }
   const attr = c.getAttribute('data-href') || c.getAttribute('data-url') || c.getAttribute('data-link');
   if (attr) { const u = parse(attr); return u ? {kind: 'attr-url', dest: u.href} : {kind: 'js', dest: ''}; }
   const oc = c.getAttribute('onclick');
   if (oc) {
     const m = oc.match(/(?:window\.)?location(?:\.href)?\s*=\s*['"]([^'"]+)['"]|location\.(?:assign|replace)\(\s*['"]([^'"]+)['"]\s*\)/);
     const u = m ? parse(m[1] || m[2]) : null;
     return u ? {kind: 'onclick-url', dest: u.href} : {kind: 'js', dest: ''};
   }
   const tog = String(c.getAttribute('data-toggle') || c.getAttribute('data-bs-toggle') || '').toLowerCase();
   if (c.getAttribute('role') === 'tab' || tog === 'tab' || tog === 'pill') {
     const id = String(c.getAttribute('aria-controls') || '').trim();
     return id && document.getElementById(id) ? {kind: 'tab', dest: ''} : {kind: 'js', dest: ''};
   }
   return {kind: 'js', dest: ''};
 };
 const flagsOf = c => {
   const f = [];
   if (c.closest('form')) f.push('form');
   if (c.hasAttribute('download')) f.push('download');
   if (String(c.getAttribute('type') || '').toLowerCase() === 'submit') f.push('submit');
   if (c.hasAttribute('data-action')) f.push('action');
   return f;
 };
 const routeOf = u => {
   const x = parse(u); if (!x) return '';
   const keys = Array.from(new Set(Array.from(x.searchParams.keys()))).sort();
   return x.pathname.replace(/\d+/g, 'N') + (keys.length ? '?' + keys.join('&') : '');
 };
 // Only id and section survive; anything else is counted (a card with extra parameters is ambiguous).
 const cleanDest = u => {
   const x = parse(u); if (!x) return {url: '', dropped: 0, host: ''};
   const k = new URL(x.origin + x.pathname);
   ['id', 'section'].forEach(n => { const v = x.searchParams.get(n); if (v !== null && /^\d{1,10}$/.test(v)) k.searchParams.set(n, v); });
   const dropped = Array.from(x.searchParams.keys()).filter(n => n !== 'id' && n !== 'section').length;
   return {url: k.href, dropped, host: x.host};
 };
 const labelOf = (box, cs) => {
   const heading = Array.from(box.querySelectorAll('h1, h2, h3, h4, h5, h6, [class*="title"]')).slice(0, 8)
     .filter(h => !h.closest(activitySelector)).map(plain).find(Boolean);
   return String(heading || cs.map(c => c.getAttribute('aria-label') || c.getAttribute('title') || plain(c)).find(Boolean) || '')
     .slice(0, 80);
 };
 const groups = new Map();
 Array.from(root.querySelectorAll(CLICK)).slice(0, 600).filter(inScope).forEach(c => {
   const box = c.closest(BOX) || c.parentElement;
   if (!groups.has(box)) groups.set(box, []);
   groups.get(box).push(c);
 });
 const recs = [];
 groups.forEach((cs, box) => {
   if (!rendered(box) || recs.length >= 60) return;
   const label = labelOf(box, cs);
   const infos = cs.map(c => Object.assign({c, f: flagsOf(c)}, destOf(c)));
   const safe = infos.filter(x => !x.f.length);
   let kind = 'blocked', dest = '', control = null;
   if (safe.length) {
     const distinct = new Set(safe.map(x => x.kind + '|' + x.dest));
     if (distinct.size === 1) { kind = safe[0].kind; dest = safe[0].dest; control = safe[0].c; }
     else kind = 'ambiguous';
   }
   const role = roleOf(label);
   const shown = role === 'target' || role === 'study';
   const clean = dest ? cleanDest(dest) : {url: '', dropped: 0, host: ''};
   recs.push({control, out: {
     key: 'k' + recs.length, role, label: role === 'other' ? '' : label, kind, tag: (control || cs[0]).tagName.toLowerCase(),
     has_href: kind === 'link' || kind === 'fragment', host: clean.host, route: dest ? routeOf(dest) : '',
     dest: shown ? clean.url : '', dropped: clean.dropped, flags: Array.from(new Set(infos.flatMap(x => x.f)))}});
 });
 if (options.mode === 'cards') {
   out.cards = recs.map(r => r.out);
   out.structure = {cards: recs.length};
   return out;
 }
 if (options.mode === 'tab_click' || options.mode === 'card_click') {
   out.clicked = false; out.reason = 'mudou';
   const r = recs.find(x => x.out.key === options.key);
   if (!r || norm(r.out.label) !== options.label) return out;
   if (r.out.role !== 'target' && r.out.role !== 'study') { out.reason = 'papel'; return out; }
   const okKinds = options.mode === 'tab_click' ? ['tab'] : ['js', 'link', 'attr-url', 'onclick-url'];
   if (!okKinds.includes(r.out.kind)) { out.reason = 'tipo'; return out; }
   if (!r.control || r.out.flags.length || !rendered(r.control)) { out.reason = 'inseguro'; return out; }
   r.control.click();
   out.clicked = true; out.reason = '';
 }
 return out;
})'''


# --- Result objects ------------------------------------------------------------------------------

@dataclass(frozen=True)
class NavQuestion:
    """The target card cannot be verified in advance; the student decides whether to trigger it once."""
    key: str
    label: str
    reason: str


@dataclass(frozen=True)
class NavReport:
    cards: tuple = ()        # structural rows only (see _structural)
    target: str = ''
    method: str = 'nenhum'
    route: str = ''
    returned: object = None  # True/False when the run left the home page, else None
    pages: int = 0
    unread: tuple = ()       # academic cards (study) not examined in this step
    informational: tuple = ()
    blocked: tuple = ()


@dataclass(frozen=True)
class Plan:
    action: str    # goto | tab | fragment | ask | blocked | unsupported | none
    why: str = ''
    url: str = ''
    method: str = ''
    route: str = ''


_KINDS = {'link', 'attr-url', 'onclick-url', 'tab', 'fragment', 'js', 'blocked', 'ambiguous', 'none'}
_METHOD_TEXT = {'link': 'link', 'attr-url': 'endereço no atributo', 'onclick-url': 'endereço no script',
                'tab': 'aba da mesma página', 'confirmed-click': 'clique confirmado pelo usuário',
                'fragment': 'âncora na mesma página', 'blocked': 'bloqueado', 'unsupported': 'não suportado',
                'nenhum': 'nenhum'}


def _text(value, limit):
    return str(value or '')[:limit]


def _clean_route(value) -> str:
    """Pattern only: no scheme/host, no values, no digits."""
    value = re.sub(r'^https?://[^/]+', '', str(value or '')).split('=')[0]
    return re.sub(r'[^A-Za-z0-9_./?&-]', '', re.sub(r'[0-9]+', 'N', value))[:120]


def _clean_card(raw):
    if not isinstance(raw, dict) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,40}', str(raw.get('key', ''))):
        return None
    role = raw.get('role') if raw.get('role') in ('target', 'study', 'info', 'blocked', 'other') else 'other'
    kind = raw.get('kind') if raw.get('kind') in _KINDS else 'none'
    flags = [f for f in (raw.get('flags') or []) if f in ('form', 'download', 'submit', 'action')]
    return dict(key=str(raw['key']), role=role, label='' if role == 'other' else clean_title(raw.get('label'))[:80],
                kind=kind, tag=re.sub(r'[^a-z0-9]', '', _text(raw.get('tag'), 12).lower()),
                has_href=bool(raw.get('has_href')), host=re.sub(r'[^A-Za-z0-9.-]', '', _text(raw.get('host'), 60)),
                route=_clean_route(raw.get('route')), dest=_text(raw.get('dest'), 2000) if role in ('target', 'study') else '',
                dropped=int(raw['dropped']) if isinstance(raw.get('dropped'), (int, float)) and 0 <= raw['dropped'] < 100 else 0,
                flags=flags)


def plan_card(card, course_id) -> Plan:
    """What would be done with this card, decided from structure only (nothing is touched)."""
    if card['role'] == 'blocked' or card['kind'] == 'blocked' or card['flags']:
        return Plan('blocked', 'cartão bloqueado (rótulo ou controle perigoso)')
    kind = card['kind']
    if kind in ('link', 'attr-url', 'onclick-url'):
        dest = classify_destination(card['dest'], course_id)
        if dest.kind == 'course':
            if card['dropped']:
                return Plan('ask', 'o endereço traz parâmetros além de id e seção', method=kind, route=dest.route)
            return Plan('goto', 'destino validado', dest.url, kind, dest.route)
        if dest.kind == 'unsupported':
            return Plan('unsupported', 'destino de módulo (página, livro ou pasta) não suportado nesta etapa',
                        method='unsupported', route=dest.route)
        if dest.kind == 'blocked':
            return Plan('blocked', f'destino bloqueado ({dest.reason})', method='blocked', route=dest.route)
        return Plan('ask', 'rota desconhecida na AEDB', method=kind, route=dest.route)
    if kind == 'fragment':
        return Plan('fragment', 'o conteúdo está na própria página', method='fragment')
    if kind == 'tab':
        return Plan('tab', 'aba da mesma página', method='tab')
    if kind == 'js':
        return Plan('ask', 'o comportamento do controle não pode ser verificado antes de acioná-lo')
    return Plan('none', 'cartão sem controle utilizável')


def _structural(card, plan, *, inspect, chosen):
    verb = ('navegaria', 'clicaria', 'pediria confirmação') if inspect else ('navegou', 'clicou', 'pediu confirmação')
    if card['role'] == 'blocked':
        decision = 'bloqueado (nunca acionado)'
    elif card['role'] == 'study' and not chosen:
        decision = 'não examinado (cartão de estudo, fora do escopo desta etapa)'
    elif card['role'] == 'info':
        decision = 'não examinado (informativo)'
    elif card['role'] == 'other':
        decision = 'ignorado'
    elif plan.action == 'goto':
        decision = f'{verb[0]} ({_METHOD_TEXT[plan.method]} validado)'
    elif plan.action == 'tab':
        decision = f'{verb[1]} ({_METHOD_TEXT["tab"]})'
    elif plan.action == 'ask':
        decision = f'{verb[2]} (destino não verificável)'
    else:
        decision = f'{plan.why}'
    return dict(role=card['role'], label=card['label'], tag=card['tag'], kind=card['kind'],
                has_href=card['has_href'], host=card['host'], route=card['route'], decision=decision)


def _av_like(name) -> bool:
    return bool(re.match(r'^\s*av\s*\d+', str(name), re.IGNORECASE))


class CardNavigator:
    def __init__(self, reader):
        self.reader = reader
        self.page = reader.page
        self.pages = 0

    # ---- primitives --------------------------------------------------------------------------
    def _nav(self, mode, cancelled, key=None, label=None):
        limits = self.reader.limits
        options = dict(mode=mode, max_elements=limits.max_elements, timeout_ms=limits.timeout_ms,
                       max_sections=MAX_EXPAND_SECTIONS + 20, lists=LISTS)
        if key is not None:
            options.update(key=key, label=label)
        return self.reader._evaluate(NAV_JS, options, cancelled)[0]

    def discover(self, cancelled=None):
        data = self._nav('cards', cancelled)
        cards, seen = [], set()
        for raw in (data.get('cards') or [])[:MAX_CARDS]:
            card = _clean_card(raw)
            if card and card['key'] not in seen:
                seen.add(card['key'])
                cards.append(card)
        return cards

    def _goto(self, url, cancelled):
        self.reader._check_cancel(cancelled)
        if self.pages >= MAX_NAV_PAGES:
            raise PilotStop('Limite de páginas visitadas atingido; a navegação foi interrompida.')
        self.pages += 1
        try:
            self.page.goto(url, wait_until='domcontentloaded', timeout=NAV_TIMEOUT_MS)
        except Exception as exc:
            # Never include the exception text: it may carry URLs and private query values.
            try:
                closed = self.page.is_closed()
            except Exception:
                closed = True
            if closed:
                raise PilotStop('Navegador fechado. Clique em Analisar para abri-lo novamente.') from None
            if exc.__class__.__name__ == 'TimeoutError':
                raise PilotStop(f'Tempo esgotado ao navegar ({NAV_TIMEOUT_MS // 1000} s). Verifique a rede e a '
                                'disponibilidade da AEDB. A sessão foi preservada; clique em Analisar para tentar '
                                'de novo.') from None
            # A redirect can abort the original navigation; the caller inspects where the page ended up.

    def _settle(self, cancelled):
        """Wait until the page is loaded and its structure stable; verifies session, course id and portal."""
        deadline = time.monotonic() + SETTLE_S
        previous, stable, data = None, 0, {}
        while True:
            data = self._nav('probe', cancelled)
            signature = (data.get('academic'), data.get('activities'))
            ready = (data.get('diag') or {}).get('ready') == 'complete'
            stable = (stable + 1 if signature == previous else 1) if ready else 0
            previous = signature
            if stable >= 2 or time.monotonic() >= deadline:
                return data
            self.reader._wait(SETTLE_POLL_MS)

    def _arrive(self, course, cancelled):
        """Confirm the academic context after moving. Returns the probe data."""
        data = self._settle(cancelled)
        if classify_destination(str(self.page.url), course.course_id).kind != 'course':
            raise PilotRejected('destino final fora da disciplina')
        return data

    def _return_home(self, course, cancelled):
        try:
            self._goto(course.url, cancelled)
            self._settle(cancelled)
        except (PilotStop, PilotLoginRequired):
            raise
        except PilotRejected:
            return False
        return classify_destination(str(self.page.url), course.course_id).url == course.url

    def _read(self, selection, cancelled, say, *, check_identity=True):
        # On a page reached through a card, links to other sections are navigation, not hidden content;
        # empty sections there are already reported as 'desconhecida'. On the home they still count.
        def announce(names):
            for name in [n for n in names if _av_like(n)][:6]:
                say(f'identificando:{name}')
        return self.reader.read(selection, cancelled=cancelled, expand=True, progress=say, on_sections=announce,
                                check_identity=check_identity, check_nav=check_identity)

    # ---- the analysis --------------------------------------------------------------------------
    def analyze(self, course, selection, *, targets=TARGET_LABELS, inspect_only=False, confirmed=None,
                declined=None, cancelled=None, progress=None):
        say = progress or (lambda state: None)
        cards = self.discover(cancelled)
        if not cards:
            if confirmed or declined:
                raise PilotRejected('Não há cartão a confirmar nesta página. Clique em Analisar novamente.')
            return self._read(selection, cancelled, say)       # an ordinary course page: read it as before
        wanted = tuple(normalize_label(t) for t in targets)
        plans = {c['key']: plan_card(c, course.course_id) for c in cards}
        target_cards = [c for c in cards if c['role'] in ('target', 'study') and normalize_label(c['label']) in wanted]
        chosen = target_cards[0] if target_cards else None
        if chosen and any((plans[c['key']].action, plans[c['key']].url) != (plans[chosen['key']].action, plans[chosen['key']].url)
                          for c in target_cards[1:]):
            plans[chosen['key']] = Plan('blocked', 'dois cartões com o mesmo rótulo levam a destinos diferentes',
                                        method='blocked')
        chosen_label = DISPLAY.get(wanted[0], targets[0]) if wanted else ''
        chosen_label = chosen['label'] if chosen else chosen_label
        unread = tuple(dict.fromkeys(c['label'] for c in cards if c['role'] == 'study' and c is not chosen
                                     and normalize_label(c['label']) not in wanted))
        info = tuple(dict.fromkeys(c['label'] for c in cards if c['role'] == 'info'))
        blocked = tuple(dict.fromkeys(c['label'] for c in cards if c['role'] == 'blocked' and c['label']))
        rows = tuple(_structural(c, plans[c['key']], inspect=inspect_only, chosen=c is chosen) for c in cards)
        base = NavReport(cards=rows, target=chosen_label, unread=unread, informational=info, blocked=blocked)
        if inspect_only:
            if chosen:
                planned = plans[chosen['key']]
                base = replace(base, method=planned.method or 'nenhum', route=planned.route)
            return self._inspection(cards, plans, base)
        keys = {c['key'] for c in target_cards}
        for token in (confirmed, declined):
            if token and token not in keys:
                raise PilotRejected('A confirmação não corresponde ao cartão pedido. Clique em Analisar novamente.')
        notes = []
        if chosen is None:
            notes.append(f'cartão {chosen_label} não encontrado entre os {len(cards)} cartões da página')
            result, report = self._read(selection, cancelled, say), base
        else:
            plan = plans[chosen['key']]
            result, report, notes = self._act(course, selection, chosen, plan, base, confirmed, declined,
                                              cancelled, say)
            if isinstance(result, NavQuestion):
                return result
        return self._finish(result, report, notes)

    def _act(self, course, selection, card, plan, base, confirmed, declined, cancelled, say):
        label = card['label']
        notes = []
        if plan.action == 'ask':
            if declined:
                notes.append('cartão não autorizado pelo usuário; a página inicial foi lida sem navegar')
                return self._read(selection, cancelled, say), replace(base, method='blocked', route=plan.route), notes
            if not confirmed:
                return NavQuestion(card['key'], label, plan.why), base, notes
            notes.append('navegação acionada por confirmação do usuário (destino não verificado de antemão)')
            return self._via_click(course, selection, card, 'card_click', 'confirmed-click', plan, base,
                                   cancelled, say, notes)
        if plan.action == 'goto':
            return self._via_address(course, selection, label, plan, base, cancelled, say, notes)
        if plan.action == 'tab':
            return self._via_click(course, selection, card, 'tab_click', 'tab', plan, base, cancelled, say, notes)
        if plan.action == 'fragment':
            notes.append('o cartão aponta para uma âncora da mesma página (nenhuma navegação)')
        else:
            notes.append(plan.why if plan.action != 'none' else 'cartão sem controle utilizável')
        return (self._read(selection, cancelled, say), replace(base, method=plan.method or 'nenhum', route=plan.route),
                notes)

    def _via_address(self, course, selection, label, plan, base, cancelled, say, notes):
        say(f'acessando:{label}')
        self._goto(plan.url, cancelled)
        try:
            probe = self._arrive(course, cancelled)
        except (PilotStop, PilotLoginRequired):
            raise
        except PilotRejected:
            notes.append('destino final fora da disciplina ou contexto não confirmado; nada foi lido nele')
            returned = self._return_home(course, cancelled)
            report = replace(base, method=plan.method, route=plan.route, returned=returned, pages=self.pages)
            result = self._read(selection, cancelled, say) if returned else self._empty(selection)
            return result, report, notes
        if not _corroborated_ids(probe, course.course_id):
            notes.append('contexto da página de destino confirmado apenas pelo endereço e pela sessão')
        result = self._read(selection, cancelled, say, check_identity=False)
        say('verificando')
        returned = self._return_home(course, cancelled)
        if not returned:
            notes.append('retorno à disciplina não confirmado')
        return result, replace(base, method=plan.method, route=plan.route, returned=returned, pages=self.pages), notes

    def _via_click(self, course, selection, card, mode, method, plan, base, cancelled, say, notes):
        label = card['label']
        say(f'acessando:{label}')
        outcome = self._nav(mode, cancelled, card['key'], normalize_label(label))
        if not outcome.get('clicked'):
            notes.append('o cartão não pôde ser acionado com segurança (' + _text(outcome.get('reason'), 20) + ')')
            return (self._read(selection, cancelled, say), replace(base, method='blocked', route=plan.route), notes)
        self.reader._wait(SETTLE_POLL_MS)
        moved = classify_destination(str(self.page.url), course.course_id).url != course.url
        try:
            self._arrive(course, cancelled)
        except (PilotStop, PilotLoginRequired):
            raise
        except PilotRejected:
            notes.append('destino final fora da disciplina ou contexto não confirmado; nada foi lido nele')
            returned = self._return_home(course, cancelled)
            report = replace(base, method=method, route=plan.route, returned=returned, pages=self.pages)
            return (self._read(selection, cancelled, say) if returned else self._empty(selection)), report, notes
        result = self._read(selection, cancelled, say, check_identity=False)
        say('verificando')
        returned = None
        if moved:
            returned = self._return_home(course, cancelled)
            if not returned:
                notes.append('retorno à disciplina não confirmado')
        return result, replace(base, method=method, route=plan.route, returned=returned, pages=self.pages), notes

    def _empty(self, selection):
        return PilotResult([], 'nao_validada', 'Nada foi lido.', coverage=None)

    # ---- result assembly -----------------------------------------------------------------------
    def _finish(self, result, report, notes):
        if result.coverage is None:
            text = ' '.join(notes)
            return replace(result, state='parcial', diagnostic=text, navigation=report)
        extra = list(notes)
        if report.unread:
            extra.append('cartão de estudo não examinado nesta etapa: ' + ', '.join(report.unread))
        state = 'parcial' if (extra and result.state == 'completa') else result.state
        text = coverage_text(result.coverage, state, tuple(result.notes) + tuple(extra), _nav_text(report))
        return replace(result, state=state, diagnostic=text, navigation=report, notes=tuple(result.notes) + tuple(extra))

    def _inspection(self, cards, plans, report):
        lines = '; '.join(
            f'[{c["role"]}] {c["tag"]} {c["kind"]} href={"sim" if c["has_href"] else "não"} '
            f'{(c["host"] + c["route"]) or "sem rota"} → {r["decision"]}'
            for c, r in zip(cards, report.cards))
        text = ('Modo de inspeção: nada foi navegado, clicado nem lido. ' + _nav_text(report) +
                f'. Estrutura dos cartões: {lines}. Estado de entrega não verificado.')
        return PilotResult([], 'nao_validada', text, coverage=None, navigation=report)


def _corroborated_ids(data, course_id) -> bool:
    ids = data.get('ids') if isinstance(data.get('ids'), dict) else {}
    return any(str(ids.get(k) or '') == str(course_id) for k in ('body', 'cfg'))


def _nav_text(report) -> str:
    kinds = Counter(c['kind'] for c in report.cards)
    parts = [f'Navegação: cartões {len(report.cards)} (' + ', '.join(f'{k} {n}' for k, n in sorted(kinds.items())) + ')']
    if report.target:
        how = _METHOD_TEXT.get(report.method, report.method)
        parts.append(f'alvo {report.target} via {how}' + (f' (rota {report.route})' if report.route else ''))
    if report.pages:
        parts.append(f'páginas visitadas {report.pages}')
    if report.returned is not None:
        parts.append('retorno à disciplina ' + ('confirmado' if report.returned else 'não confirmado'))
    if report.unread:
        parts.append('não examinados (fora do escopo desta etapa): ' + ', '.join(report.unread))
    if report.informational:
        parts.append('informativos não lidos: ' + ', '.join(report.informational))
    if report.blocked:
        parts.append('bloqueados (nunca acionados): ' + ', '.join(report.blocked))
    return '; '.join(parts)
