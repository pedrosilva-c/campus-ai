"""Chrome Native Messaging host side of the future Campus AI Companion extension (draft).

Status: implemented and tested with local byte streams only. No native host is registered in the
Windows registry and no extension has been loaded in Chrome; registering one writes HKCU and needs the
student's explicit authorization (see ARCHITECTURE_3.md).

Trust model
-----------
* Chrome only launches a host for extensions listed in the host manifest's ``allowed_origins``, and
  passes the caller origin as the first argument. ``caller_origin`` re-checks it against a configured
  allow-list and fails closed while that list is empty.
* The channel is a private stdin/stdout pipe per launch. On top of it a session handshake
  (``hello`` -> ``welcome`` with a random token) orders the conversation and request ids stop replays.
* The extension can only REPORT data: ``hello`` and ``page_report``. There is no message that asks
  the host to run, open, fetch, write, delete or submit anything; unknown types or fields are rejected.
* Every snapshot passes ``contract.parse_snapshot`` and must be attributed to ``companion`` and limited
  to authorized courses. Responses carry codes and counts only, never page content.
"""
from __future__ import annotations

import json
import re
import secrets
import struct
from collections import deque
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from . import contract

PROTOCOL_ID = 'campus-ai.companion/1'
HOST_NAME = 'br.campus_ai.companion'
# Stable id of the Campus AI Companion (derived from the public "key" in companion/manifest.json; a test
# recomputes it). The only extension the host accepts.
COMPANION_EXTENSION_ID = 'oglmhecabakelhiaiandpdonpblldhnn'
MAX_MESSAGE_BYTES = 512 * 1024     # inbound cap (Chrome would allow up to 64 MiB)
MAX_RESPONSE_BYTES = 16 * 1024     # outbound cap (Chrome's hard limit is 1 MB)
MAX_DEPTH = 12
MAX_REJECTIONS = 5
MAX_REMEMBERED_IDS = 1000
CAPABILITIES = frozenset({'page_report'})
REPORTABLE_PAGES = {'curso_inicio': '/ava/course/view.php?id', 'curso_secao': '/ava/course/view.php?id&section',
                    # format-tiles: the page a tile opens. Its ?id is a SECTION id, not the course id.
                    'curso_bloco': '/ava/course/section.php?id'}

_EXTENSION_ID = re.compile(r'[a-p]{32}')
_ORIGIN = re.compile(r'chrome-extension://([a-p]{32})/')
_REQUEST_ID = re.compile(r'[A-Za-z0-9-]{8,64}')
_VERSION = re.compile(r'[0-9]{1,4}(\.[0-9]{1,4}){0,3}')
_TOKEN = re.compile(r'[0-9a-f]{32}')
_ENVELOPE = ('protocol', 'type', 'request_id', 'session', 'payload')


class ProtocolError(ValueError):
    def __init__(self, code: str, detail: str = ''):
        super().__init__(code)
        self.code = code
        self.detail = detail[:200]


class FramingError(ProtocolError):
    """The byte stream cannot be trusted any more: the host must stop."""


# --- Page classification (mirrored by companion/src/classify.js; shared fixture keeps them equal) --

@dataclass(frozen=True)
class PageInfo:
    kind: str
    route: str = ''
    moodle_id: str = ''


_ACTIVITY_MODULES = '|'.join(sorted(contract.ACTIVITY_KINDS))
_READ_MODULE = re.compile(r'/ava/mod/(page|book|folder)/view\.php')
_ACTIVITY_MODULE = re.compile(rf'/ava/mod/({_ACTIVITY_MODULES})/view\.php')
_FILE_MODULE = re.compile(r'/ava/mod/(resource|url|imscp)/view\.php')   # downloads / redirects


def route_pattern(path: str, query: str) -> str:
    keys = sorted(set(parse_qs(query, keep_blank_values=True)))
    return re.sub(r'[0-9]+', 'N', path) + ('?' + '&'.join(keys) if keys else '')


def classify_page(url: str) -> PageInfo:
    """Classify an address. Only structure leaves this function: never ids other than the course's."""
    try:
        p = urlsplit(str(url))
        host, port = p.hostname, p.port
    except ValueError:
        return PageInfo('invalida')
    if p.scheme != 'https' or host != contract.AEDB_HOST or port is not None or p.username or p.password:
        return PageInfo('externa')
    route = route_pattern(p.path, p.query)
    if p.path == '/ava/course/view.php':
        q = parse_qs(p.query, keep_blank_values=True)
        if (set(q) <= {'id', 'section'} and all(len(v) == 1 for v in q.values())
                and re.fullmatch(r'[1-9][0-9]{0,9}', q.get('id', [''])[0])
                and re.fullmatch(r'[0-9]{1,6}', q.get('section', ['0'])[0])):
            return PageInfo('curso_secao' if 'section' in q else 'curso_inicio', route, q['id'][0])
        return PageInfo('outra_aedb', route)
    if p.path == '/ava/course/section.php':
        q = parse_qs(p.query, keep_blank_values=True)
        if set(q) == {'id'} and len(q['id']) == 1 and re.fullmatch(r'[1-9][0-9]{0,9}', q['id'][0]):
            return PageInfo('curso_bloco', route)      # course identity is proven by the page, not the URL
        return PageInfo('outra_aedb', route)
    if _READ_MODULE.fullmatch(p.path):
        return PageInfo('modulo_leitura', route)
    if _ACTIVITY_MODULE.fullmatch(p.path):
        return PageInfo('modulo_atividade', route)
    if _FILE_MODULE.fullmatch(p.path):
        return PageInfo('modulo_arquivo', route)
    if p.path.startswith('/ava/login/'):
        return PageInfo('login', route)
    if p.path.startswith('/ava/calendar/'):
        return PageInfo('calendario', route)
    return PageInfo('outra_aedb', route)


# --- Framing ----------------------------------------------------------------------------------------

def _read_exact(stream, n: int) -> bytes:
    data = b''
    while len(data) < n:
        chunk = stream.read(n - len(data))
        if not chunk:
            break
        data += chunk
    return data


def read_frame(stream) -> bytes | None:
    """One message: 4-byte little-endian length + UTF-8 JSON. None on a clean end of stream."""
    header = _read_exact(stream, 4)
    if not header:
        return None
    if len(header) < 4:
        raise FramingError('quadro_invalido')
    (length,) = struct.unpack('<I', header)
    if length > MAX_MESSAGE_BYTES:
        raise FramingError('grande_demais')      # body is never read
    body = _read_exact(stream, length)
    if len(body) != length:
        raise FramingError('quadro_invalido')
    return body


def encode_frame(obj) -> bytes:
    raw = json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProtocolError('resposta_grande_demais')
    return struct.pack('<I', len(raw)) + raw


def _no_duplicates(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ProtocolError('mensagem_invalida', 'chave repetida')
    return dict(pairs)


def _reject_constant(_):
    raise ProtocolError('mensagem_invalida', 'constante não permitida')


def _depth(value, level=0):
    if level > MAX_DEPTH:
        raise ProtocolError('mensagem_invalida', 'aninhamento excessivo')
    if isinstance(value, dict):
        for v in value.values():
            _depth(v, level + 1)
    elif isinstance(value, list):
        for v in value:
            _depth(v, level + 1)


def decode_json(raw: bytes) -> dict:
    try:
        text = raw.decode('utf-8', errors='strict')
        value = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except ProtocolError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise ProtocolError('mensagem_invalida', 'JSON inválido') from None
    _depth(value)
    if not isinstance(value, dict):
        raise ProtocolError('mensagem_invalida', 'objeto esperado')
    return value


# --- Caller origin ----------------------------------------------------------------------------------

def caller_origin(argv, allowed_extension_ids) -> str:
    """Chrome passes 'chrome-extension://<id>/' as the first argument. Empty allow-list = refuse all."""
    allowed = {i for i in allowed_extension_ids if _EXTENSION_ID.fullmatch(str(i))}
    if not allowed or not argv:
        raise ProtocolError('origem_recusada')
    m = _ORIGIN.fullmatch(str(argv[0]))
    if not m or m.group(1) not in allowed:
        raise ProtocolError('origem_recusada')
    return m.group(1)


# --- Session ----------------------------------------------------------------------------------------

class CompanionSession:
    """State machine for one launch of the host.

    ``sink(snapshot)`` receives each validated Snapshot. When it returns an object with ``as_reply()`` (the
    persistence result, produced only after a COMMIT), the ack says ``saved: true`` with those numbers;
    otherwise ``saved: false``. If the sink raises, the report is rejected (``falha_persistencia`` or the
    sink's own code) and nothing is claimed. ``on_reject(code)`` is told about every rejected page_report.
    """

    def __init__(self, allowed_courses, sink, *, token_factory=None, on_reject=None):
        self.allowed_scope = {contract.course_uid(c) for c in allowed_courses}
        self.sink = sink
        self.on_reject = on_reject
        self.token_factory = token_factory or (lambda: secrets.token_hex(16))
        self.token = None
        self.seen = deque(maxlen=MAX_REMEMBERED_IDS)
        self.reports_done = 0

    def _reply(self, type_, request_id='', **extra):
        return {'protocol': PROTOCOL_ID, 'type': type_, 'request_id': request_id, **extra}

    def handle(self, raw: bytes) -> dict:
        request_id = ''
        kind = ''
        try:
            msg = decode_json(raw)
            if set(msg) != set(_ENVELOPE):
                raise ProtocolError('mensagem_invalida', 'envelope inválido')
            if msg['protocol'] != PROTOCOL_ID:
                raise ProtocolError('protocolo_nao_suportado')
            if not isinstance(msg['request_id'], str) or not _REQUEST_ID.fullmatch(msg['request_id']):
                raise ProtocolError('mensagem_invalida', 'request_id inválido')
            request_id = msg['request_id']
            if request_id in self.seen:
                raise ProtocolError('repetida')
            self.seen.append(request_id)
            kind = msg['type'] if msg['type'] in ('hello', 'page_report') else ''
            if not isinstance(msg['payload'], dict) or not isinstance(msg['session'], str):
                raise ProtocolError('mensagem_invalida', 'payload inválido')
            if msg['type'] == 'hello':
                return self._hello(msg, request_id)
            if msg['type'] == 'page_report':
                return self._page_report(msg, request_id)
            raise ProtocolError('tipo_desconhecido')
        except ProtocolError as exc:
            if kind == 'page_report' and self.on_reject is not None:
                try:
                    self.on_reject(exc.code)
                except Exception:       # recording a failure must never break the reply
                    pass
            return self._reply('rejected', request_id, code=exc.code, detail=exc.detail)

    def _hello(self, msg, request_id):
        if self.token is not None:
            raise ProtocolError('sessao_ja_iniciada')
        payload = msg['payload']
        if (set(payload) != {'extension_version', 'capabilities'}
                or not isinstance(payload['extension_version'], str)
                or not _VERSION.fullmatch(payload['extension_version'])
                or not isinstance(payload['capabilities'], list)
                or not all(isinstance(c, str) for c in payload['capabilities'])
                or not set(payload['capabilities']) <= CAPABILITIES):
            raise ProtocolError('mensagem_invalida', 'hello inválido')
        token = self.token_factory()
        if not _TOKEN.fullmatch(token):
            raise ProtocolError('erro_interno')
        self.token = token
        return self._reply('welcome', request_id, session=token, capabilities=sorted(CAPABILITIES))

    def _page_report(self, msg, request_id):
        if self.token is None or not secrets.compare_digest(msg['session'], self.token):
            raise ProtocolError('sessao_invalida')
        payload = msg['payload']
        if set(payload) != {'page', 'snapshot'} or not isinstance(payload['page'], dict):
            raise ProtocolError('esquema_invalido', 'payload')
        page = payload['page']
        if set(page) != {'kind', 'route'} or REPORTABLE_PAGES.get(page['kind']) != page['route']:
            raise ProtocolError('esquema_invalido', 'página não reportável')
        raw_scope = payload['snapshot'].get('scope') if isinstance(payload['snapshot'], dict) else None
        if not isinstance(raw_scope, list) or not raw_scope or \
                not all(isinstance(s, str) and s in self.allowed_scope for s in raw_scope):
            raise ProtocolError('disciplina_nao_autorizada')
        try:
            snap = contract.parse_snapshot(payload['snapshot'])
        except contract.ContractError as exc:
            raise ProtocolError('esquema_invalido', str(exc)) from None
        records = [*snap.courses, *snap.sections, *snap.materials, *snap.activities, *snap.events,
                   *snap.announcements]
        if any(r.provenance.source != 'companion' for r in records) or \
                any(s.source != 'companion' for s in snap.sources):
            raise ProtocolError('esquema_invalido', 'origem dos dados deve ser companion')
        try:
            outcome = self.sink(snap)
        except Exception as exc:        # never echo the error text: only a fixed code
            code = getattr(exc, 'code', '')
            raise ProtocolError(code if isinstance(code, str) and re.fullmatch(r'[a-z_]{1,40}', code)
                                else 'falha_persistencia') from None
        self.reports_done += 1
        counts = {'materials': len(snap.materials), 'activities': len(snap.activities)}
        if hasattr(outcome, 'as_reply'):
            return self._reply('ack', request_id, counts=counts, saved=True, result=outcome.as_reply())
        return self._reply('ack', request_id, counts=counts, saved=False)


def run_host(argv, stdin, stdout, *, allowed_extension_ids, allowed_courses, sink, token_factory=None,
             on_reject=None) -> int:
    """Serve one Chrome launch: one hello and ONE accepted report, then exit.

    Exit codes: 0 done or end of stream, 1 origin refused, 2 framing, 3 abuse.
    """
    try:
        caller_origin(argv, allowed_extension_ids)
    except ProtocolError:
        return 1
    session = CompanionSession(allowed_courses, sink, token_factory=token_factory, on_reject=on_reject)
    rejections = 0

    def send(reply):
        stdout.write(encode_frame(reply))
        stdout.flush()

    while True:
        try:
            raw = read_frame(stdin)
        except FramingError as exc:
            send(session._reply('rejected', code=exc.code, detail=''))
            return 2
        if raw is None:
            return 0
        reply = session.handle(raw)
        send(reply)
        if session.reports_done:
            return 0
        if reply['type'] == 'rejected':
            rejections += 1
            if rejections >= MAX_REJECTIONS:
                return 3
