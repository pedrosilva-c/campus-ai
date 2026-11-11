"""Chrome Native Messaging host side of the (future) Campus AI Companion. Local streams only."""
import io
import json
import struct
import unittest
from pathlib import Path

from campus_ai import companion_protocol as cp
from campus_ai import contract

FIXTURES = Path(__file__).parent / 'fixtures'
EXT_ID = 'a' * 32
ORIGIN = f'chrome-extension://{EXT_ID}/'


def frame(obj) -> bytes:
    raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode('utf-8')
    return struct.pack('<I', len(raw)) + raw


def companion_snapshot():
    data = json.loads((FIXTURES / 'contract' / 'snapshot_ficticio.json').read_text(encoding='utf-8'))
    data['events'] = []
    for table in ('courses', 'sections', 'materials', 'activities', 'announcements'):
        for rec in data[table]:
            rec['provenance']['source'] = 'companion'
    data['sources'] = [{'source': 'companion', 'last_attempt': data['generated_at'],
                        'last_success': data['generated_at'], 'status': 'parcial', 'message': ''}]
    return data


def envelope(type_, payload, *, session='', request_id='req-00000001'):
    return {'protocol': cp.PROTOCOL_ID, 'type': type_, 'request_id': request_id, 'session': session,
            'payload': payload}


HELLO = envelope('hello', {'extension_version': '0.0.1', 'capabilities': ['page_report']})


def report(session, request_id='req-00000002', snapshot=None, page=None):
    return envelope('page_report', {'page': page or {'kind': 'curso_inicio', 'route': '/ava/course/view.php?id'},
                                    'snapshot': snapshot or companion_snapshot()},
                    session=session, request_id=request_id)


class PageClassificationTests(unittest.TestCase):
    def test_shared_cases(self):
        cases = json.loads((FIXTURES / 'companion' / 'page_cases.json').read_text(encoding='utf-8'))
        for case in cases:
            info = cp.classify_page(case['url'])
            self.assertEqual((info.kind, info.route, info.moodle_id),
                             (case['kind'], case['route'], case['moodle_id']), case['url'])

    def test_route_never_carries_values(self):
        info = cp.classify_page('https://ead.aedb.br/ava/calendar/export_execute.php?userid=1&authtoken=SEGREDO')
        self.assertNotIn('SEGREDO', info.route)
        self.assertNotIn('1', info.route)


class FramingTests(unittest.TestCase):
    def test_round_trip(self):
        stream = io.BytesIO(cp.encode_frame({'a': 'ç'}))
        self.assertEqual(json.loads(cp.read_frame(stream)), {'a': 'ç'})
        self.assertIsNone(cp.read_frame(stream))

    def test_oversized_header_rejected_without_reading_body(self):
        class Spy(io.BytesIO):
            requested = []

            def read(self, n=-1):
                self.requested.append(n)
                return super().read(n)
        stream = Spy(struct.pack('<I', cp.MAX_MESSAGE_BYTES + 1) + b'x' * 10)
        with self.assertRaises(cp.FramingError) as ctx:
            cp.read_frame(stream)
        self.assertEqual(ctx.exception.code, 'grande_demais')
        self.assertEqual(stream.requested, [4])

    def test_truncated_frames(self):
        for data in (b'\x05\x00', struct.pack('<I', 10) + b'abc'):
            with self.assertRaises(cp.FramingError):
                cp.read_frame(io.BytesIO(data))

    def test_response_size_cap(self):
        with self.assertRaises(cp.ProtocolError):
            cp.encode_frame({'x': 'y' * cp.MAX_RESPONSE_BYTES})


class DecodeTests(unittest.TestCase):
    def test_rejects_malformed_json(self):
        bad = [b'\xff\xfe', b'{"a":1,"a":2}', b'[1,2]', b'{"a": NaN}', b'not json',
               b'{"a":' * (cp.MAX_DEPTH + 2) + b'1' + b'}' * (cp.MAX_DEPTH + 2)]
        for raw in bad:
            with self.assertRaises(cp.ProtocolError, msg=raw[:20]):
                cp.decode_json(raw)


class OriginTests(unittest.TestCase):
    def test_accepts_exact_allowed_origin(self):
        self.assertEqual(cp.caller_origin([ORIGIN, '--parent-window=0'], {EXT_ID}), EXT_ID)

    def test_rejects(self):
        for argv, allowed in (([], {EXT_ID}), (['--parent-window=0'], {EXT_ID}),
                              ([f'chrome-extension://{"b" * 32}/'], {EXT_ID}),
                              (['https://ead.aedb.br/'], {EXT_ID}),
                              ([ORIGIN + 'x'], {EXT_ID}),
                              ([ORIGIN], set())):          # fail closed while no id is configured
            with self.assertRaises(cp.ProtocolError, msg=argv):
                cp.caller_origin(argv, allowed)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.received = []
        self.session = cp.CompanionSession({'7653'}, self.received.append, token_factory=lambda: 'f' * 32)

    def send(self, obj):
        raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        return self.session.handle(raw)

    def open(self):
        welcome = self.send(HELLO)
        self.assertEqual(welcome['type'], 'welcome')
        return welcome['session']

    def test_happy_path(self):
        token = self.open()
        ack = self.send(report(token))
        self.assertEqual(ack['type'], 'ack', ack)
        self.assertEqual(len(self.received), 1)
        self.assertIsInstance(self.received[0], contract.Snapshot)
        self.assertEqual(ack['counts'], {'materials': 1, 'activities': 2})

    def test_report_requires_hello_and_matching_session(self):
        self.assertEqual(self.send(report('f' * 32))['code'], 'sessao_invalida')
        self.open()
        self.assertEqual(self.send(report('0' * 32, 'req-00000007'))['code'], 'sessao_invalida')
        self.assertEqual(self.received, [])

    def test_second_hello_rejected(self):
        self.open()
        self.assertEqual(self.send(dict(HELLO, request_id='req-00000009'))['code'], 'sessao_ja_iniciada')

    def test_replay_rejected(self):
        token = self.open()
        self.assertEqual(self.send(report(token))['type'], 'ack')
        self.assertEqual(self.send(report(token))['code'], 'repetida')
        self.assertEqual(len(self.received), 1)

    def test_unknown_types_and_fields_rejected(self):
        token = self.open()
        for i, msg in enumerate([
                envelope('execute', {'code': 'rm -rf'}, session=token),
                envelope('eval', {}, session=token),
                dict(report(token), command='open'),
                dict(report(token), protocol='campus-ai.companion/2'),
                envelope('hello', {'extension_version': '1', 'capabilities': ['shell']}),
        ]):
            msg['request_id'] = f'req-1000000{i}'
            self.assertEqual(self.send(msg)['type'], 'rejected', msg['type'])
        self.assertEqual(self.received, [])

    def test_bad_request_id(self):
        self.assertEqual(self.send(dict(HELLO, request_id='x'))['type'], 'rejected')

    def test_snapshot_must_come_from_companion_and_authorized_course(self):
        token = self.open()
        wrong_source = companion_snapshot()
        wrong_source['activities'][0]['provenance']['source'] = 'moodle_api'
        self.assertEqual(self.send(report(token, 'req-00000003', wrong_source))['code'], 'esquema_invalido')
        other = companion_snapshot()
        other['scope'] = ['moodle:course:9999']
        self.assertEqual(self.send(report(token, 'req-00000004', other))['code'], 'disciplina_nao_autorizada')
        self.assertEqual(self.received, [])

    def test_page_kind_must_match_content_script_scope(self):
        token = self.open()
        for i, page in enumerate([{'kind': 'modulo_atividade', 'route': '/ava/mod/assign/view.php?id'},
                                  {'kind': 'curso_inicio', 'route': '/ava/mod/assign/view.php?id'},
                                  {'kind': 'curso_inicio', 'route': '/ava/course/view.php?id=7653'}]):
            self.assertEqual(self.send(report(token, f'req-2000000{i}', page=page))['code'], 'esquema_invalido')

    def test_responses_never_echo_content(self):
        token = self.open()
        snap = companion_snapshot()
        snap['activities'][0]['title'] = 'Título-sigiloso-XYZ'
        snap['activities'][0]['kind'] = 'nao-existe'
        response = json.dumps(self.send(report(token, 'req-00000005', snap)))
        self.assertNotIn('sigiloso', response)
        self.assertNotIn('nao-existe', response)


class RunHostTests(unittest.TestCase):
    def run_host(self, data, argv=(ORIGIN,), allowed=frozenset({EXT_ID})):
        out, received = io.BytesIO(), []
        code = cp.run_host(list(argv), io.BytesIO(data), out, allowed_extension_ids=allowed,
                           allowed_courses={'7653'}, sink=received.append, token_factory=lambda: 'e' * 32)
        out.seek(0)
        replies = []
        while (raw := cp.read_frame(out)) is not None:
            replies.append(json.loads(raw))
        return code, replies, received

    def test_end_to_end(self):
        code, replies, received = self.run_host(frame(HELLO) + frame(report('e' * 32)))
        self.assertEqual(code, 0)
        self.assertEqual([r['type'] for r in replies], ['welcome', 'ack'])
        self.assertEqual(len(received), 1)

    def test_refuses_unknown_origin_without_reading(self):
        code, replies, received = self.run_host(frame(HELLO), argv=['chrome-extension://' + 'c' * 32 + '/'])
        self.assertEqual((code, replies, received), (1, [], []))

    def test_fail_closed_without_configured_extension(self):
        code, _, _ = self.run_host(frame(HELLO), allowed=frozenset())
        self.assertEqual(code, 1)

    def test_framing_error_stops(self):
        code, replies, _ = self.run_host(frame(HELLO) + struct.pack('<I', cp.MAX_MESSAGE_BYTES + 1))
        self.assertEqual(code, 2)
        self.assertEqual([r['type'] for r in replies], ['welcome', 'rejected'])

    def test_too_many_rejections_stop(self):
        junk = b''.join(frame(b'{"bad": true}') for _ in range(cp.MAX_REJECTIONS + 3))
        code, replies, _ = self.run_host(junk)
        self.assertEqual(code, 3)
        self.assertEqual(len(replies), cp.MAX_REJECTIONS)


if __name__ == '__main__':
    unittest.main()
