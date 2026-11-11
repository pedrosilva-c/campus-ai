"""The Native Messaging host end to end (python -m campus_ai.companion_host), with in-memory pipes and a
temporary database. Nothing is registered in Windows; fictitious snapshots only."""
import base64
import hashlib
import io
import json
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companion_snapshots import ITEMS, snapshot_dict  # noqa: E402

from campus_ai import companion_host, companion_protocol as cp  # noqa: E402
from campus_ai.companion_store import SnapshotStore, read_summary  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which('node')
ORIGIN = f'chrome-extension://{cp.COMPANION_EXTENSION_ID}/'
TOKEN = 'c' * 32
PAGE = {'kind': 'curso_inicio', 'route': '/ava/course/view.php?id'}


def frame(obj) -> bytes:
    raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode('utf-8')
    return struct.pack('<I', len(raw)) + raw


def hello(request_id='req-00000001'):
    return {'protocol': cp.PROTOCOL_ID, 'type': 'hello', 'request_id': request_id, 'session': '',
            'payload': {'extension_version': '0.3.0', 'capabilities': ['page_report']}}


def report(snapshot, request_id='req-00000002', page=PAGE):
    return {'protocol': cp.PROTOCOL_ID, 'type': 'page_report', 'request_id': request_id, 'session': TOKEN,
            'payload': {'page': page, 'snapshot': snapshot}}


class FakeTimer:
    instances = []

    def __init__(self, seconds, action):
        self.seconds, self.action, self.started, self.cancelled = seconds, action, False, False
        FakeTimer.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class HostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'live.db'
        FakeTimer.instances.clear()

    def run_host(self, data: bytes, argv=(ORIGIN, '--parent-window=0'), db=None):
        out = io.BytesIO()
        code = companion_host.main(list(argv), io.BytesIO(data), out, db_path=db or self.db, courses=['7653'],
                                   timer=FakeTimer, token_factory=lambda: TOKEN)
        out.seek(0)
        replies = []
        while (raw := cp.read_frame(out)) is not None:
            replies.append(json.loads(raw))
        return code, replies

    def runs(self):
        with closing(sqlite3.connect(self.db)) as db:
            return db.execute('SELECT status, error, items, novos, inalterados FROM companion_runs ORDER BY id').fetchall()

    def test_extension_id_matches_the_manifest_key(self):
        manifest = json.loads((ROOT / 'companion' / 'manifest.json').read_text(encoding='utf-8'))
        digest = hashlib.sha256(base64.b64decode(manifest['key'])).hexdigest()[:32]
        self.assertEqual(''.join(chr(ord('a') + int(c, 16)) for c in digest), cp.COMPANION_EXTENSION_ID)

    def test_unknown_caller_is_refused_before_the_database_is_touched(self):
        for argv in ([], ['chrome-extension://' + 'b' * 32 + '/'], ['https://ead.aedb.br/']):
            code, replies = self.run_host(frame(hello()) + frame(report(snapshot_dict())), argv=argv)
            self.assertEqual((code, replies), (1, []))
        self.assertFalse(self.db.exists())
        self.assertEqual(FakeTimer.instances, [])

    def test_first_sync_is_confirmed_only_after_it_is_stored(self):
        code, replies = self.run_host(frame(hello()) + frame(report(snapshot_dict())))
        self.assertEqual(code, 0)
        self.assertEqual([r['type'] for r in replies], ['welcome', 'ack'])
        ack = replies[1]
        self.assertEqual(ack['request_id'], 'req-00000002')
        self.assertIs(ack['saved'], True)
        self.assertEqual(ack['result'], {'run': 1, 'itens': 7, 'novos': 7, 'alterados': 0, 'ausentes': 0,
                                         'reaparecidos': 0, 'inalterados': 0})
        self.assertEqual(self.runs(), [('ok', '', 7, 7, 0)])
        self.assertEqual(read_summary(self.db)['last']['items'], 7)
        self.assertTrue(FakeTimer.instances[0].started and FakeTimer.instances[0].cancelled)

    def test_second_sync_and_one_report_per_launch(self):
        self.run_host(frame(hello()) + frame(report(snapshot_dict())))
        twice = frame(hello()) + frame(report(snapshot_dict())) + frame(report(snapshot_dict(), 'req-00000003'))
        code, replies = self.run_host(twice)
        self.assertEqual(code, 0)
        self.assertEqual([r['type'] for r in replies], ['welcome', 'ack'])   # the extra report is never read
        self.assertEqual(replies[1]['result']['inalterados'], 7)
        self.assertEqual(len(self.runs()), 2)

    def test_duplicated_message_is_rejected(self):
        code, replies = self.run_host(frame(hello()) + frame(hello()) + frame(report(snapshot_dict())))
        self.assertEqual([r['type'] for r in replies], ['welcome', 'rejected', 'ack'])
        self.assertEqual(replies[1]['code'], 'repetida')

    def test_invalid_schema_and_unauthorized_course_are_rejected_and_logged_without_content(self):
        bad = snapshot_dict()
        bad['activities'][0]['kind'] = 'Conteúdo-sigiloso-XYZ'
        for snap, expected in ((bad, 'esquema_invalido'), (snapshot_dict(course='9999'), 'disciplina_nao_autorizada')):
            code, replies = self.run_host(frame(hello()) + frame(report(snap)))
            self.assertEqual(replies[-1]['type'], 'rejected')
            self.assertEqual(replies[-1]['code'], expected)
            self.assertNotIn('sigiloso', json.dumps(replies))
        self.assertEqual([(s, e) for s, e, *_ in self.runs()],
                         [('erro', 'esquema_invalido'), ('erro', 'disciplina_nao_autorizada')])
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM companion_items').fetchone()[0], 0)
            self.assertNotIn('sigiloso', ' '.join(str(r) for r in db.execute('SELECT * FROM companion_runs')))

    def test_disconnection_or_cancellation_stores_nothing(self):
        code, replies = self.run_host(frame(hello()))                                # popup closed after hello
        self.assertEqual((code, [r['type'] for r in replies]), (0, ['welcome']))
        raw = frame(report(snapshot_dict()))
        code, replies = self.run_host(frame(hello()) + raw[:len(raw) // 2])          # cut in the middle
        self.assertEqual(code, 2)
        self.assertEqual(replies[-1]['code'], 'quadro_invalido')
        code, _ = self.run_host(b'')                                                  # nothing at all
        self.assertEqual(code, 0)
        self.assertEqual(self.runs(), [])

    def test_sqlite_failure_is_reported_and_nothing_is_claimed(self):
        with patch.object(SnapshotStore, 'save', side_effect=sqlite3.OperationalError('disco cheio (simulado)')):
            code, replies = self.run_host(frame(hello()) + frame(report(snapshot_dict())))
        self.assertEqual(replies[-1]['type'], 'rejected')
        self.assertEqual(replies[-1]['code'], 'falha_persistencia')
        self.assertNotIn('saved', replies[-1])
        self.assertNotIn('disco', json.dumps(replies))
        self.assertEqual([(s, e) for s, e, *_ in self.runs()], [('erro', 'falha_persistencia')])

    def test_permission_failure(self):
        with patch.object(SnapshotStore, 'save', side_effect=PermissionError('acesso negado (simulado)')):
            _, replies = self.run_host(frame(hello()) + frame(report(snapshot_dict())))
        self.assertEqual(replies[-1]['code'], 'sem_permissao')

    def test_unavailable_database(self):
        _, replies = self.run_host(frame(hello()) + frame(report(snapshot_dict())), db=Path(self.tmp.name))
        self.assertEqual(replies[-1]['code'], 'banco_indisponivel')

    def test_items_of_the_section_absent_in_a_later_reading(self):
        self.run_host(frame(hello()) + frame(report(snapshot_dict())))
        _, replies = self.run_host(frame(hello()) + frame(report(snapshot_dict(ITEMS[:5]))))
        self.assertEqual(replies[-1]['result']['ausentes'], 2)

    def test_registration_status_is_a_read_only_lookup(self):
        # Independent of the machine: 'registrado' once the student activated the host, else 'nao_registrado'.
        first = companion_host.registration_status()
        self.assertIn(first, ('registrado', 'nao_registrado', 'indisponivel'))
        self.assertEqual(companion_host.registration_status(), first)       # asking changes nothing


@unittest.skipUnless(NODE, 'Node.js não encontrado')
class JsToHostTests(unittest.TestCase):
    def test_what_the_extension_builds_is_stored_by_the_host(self):
        projection = json.loads((ROOT / 'tests' / 'fixtures' / 'companion' / 'tiles_projection.json').read_text('utf-8'))
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp-campus-ai') as tmp:
            path = Path(tmp) / 'p.json'
            path.write_text(json.dumps(projection), encoding='utf-8')
            proc = subprocess.run([NODE, str(ROOT / 'companion' / 'test' / 'emit_tiles.mjs'), str(path), TOKEN,
                                   'https://ead.aedb.br/ava/course/section.php?id=4242'],
                                  capture_output=True, text=True, encoding='utf-8', timeout=60, cwd=ROOT)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            messages = [json.loads(line) for line in proc.stdout.splitlines()][1:]     # hello, page_report
            out = io.BytesIO()
            code = companion_host.main([ORIGIN], io.BytesIO(b''.join(frame(m) for m in messages)), out,
                                       db_path=Path(tmp) / 'live.db', courses=['7653'], timer=FakeTimer,
                                       token_factory=lambda: TOKEN)
            out.seek(0)
            replies = []
            while (raw := cp.read_frame(out)) is not None:
                replies.append(json.loads(raw))
            self.assertEqual(code, 0)
            self.assertEqual(replies[-1]['type'], 'ack')
            self.assertEqual(replies[-1]['result']['novos'], 7)
            self.assertEqual(read_summary(Path(tmp) / 'live.db')['last']['section_name'], 'Atividades Avaliativas')


if __name__ == '__main__':
    unittest.main()
