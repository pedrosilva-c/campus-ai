"""Format-tiles adapter of the Companion: JS output validated by the Python contract and host.

* Always (needs Node, already used by the suite): the adapter's snapshot is accepted by
  contract.parse_snapshot and by the Native Messaging host session, uids match the existing connectors,
  fingerprints do not churn between reads, and nothing is sent when identity/format cannot be confirmed.
* Opt-in (CAMPUS_AI_BROWSER_SMOKE=1): the DOM projection and content script run in local Chromium against
  synthetic HTML. Every request is aborted except the fictitious page, which is served from memory.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from campus_ai import companion_protocol as cp
from campus_ai import contract

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / 'companion'
FIXTURES = ROOT / 'tests' / 'fixtures' / 'companion'
GOLDEN = FIXTURES / 'tiles_projection.json'
NODE = shutil.which('node')
PAGE_URL = 'https://ead.aedb.br/ava/course/section.php?id=4242'
TOKEN = 'd' * 32


def emit(projection, tmp, url=PAGE_URL):
    path = Path(tmp) / 'projection.json'
    path.write_text(json.dumps(projection), encoding='utf-8')
    proc = subprocess.run([NODE, str(EXT / 'test' / 'emit_tiles.mjs'), str(path), TOKEN, url],
                          capture_output=True, text=True, encoding='utf-8', timeout=60, cwd=ROOT)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return [json.loads(line) for line in proc.stdout.splitlines() if line]


def golden():
    return json.loads(GOLDEN.read_text(encoding='utf-8'))


@unittest.skipUnless(NODE, 'Node.js não encontrado; testes do adaptador ignorados')
class AdapterOutputTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / '.tmp-campus-ai'
        scratch.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.tmp.cleanup)
        self.lines = emit(golden(), self.tmp.name)
        self.result = self.lines[0]
        self.snapshot = contract.parse_snapshot(self.result['snapshot'])

    def test_contract_accepts_the_adapter_output(self):
        self.assertTrue(self.result['ok'])
        self.assertEqual(self.snapshot.coverage.state, 'parcial')
        self.assertEqual((len(self.snapshot.materials), len(self.snapshot.activities)), (1, 6))
        self.assertEqual(contract.parse_snapshot(contract.snapshot_to_dict(self.snapshot)), self.snapshot)

    def test_uids_are_the_ones_the_existing_connectors_produce(self):
        cmids = {r.uid.rsplit(':', 1)[1] for r in (*self.snapshot.materials, *self.snapshot.activities)}
        self.assertEqual(cmids, {'90001', '90002', '90003', '90004', '90005', '90006', '90007'})
        for record in (*self.snapshot.materials, *self.snapshot.activities):
            self.assertEqual(record.uid, contract.module_uid('7653', record.uid.rsplit(':', 1)[1]))
        # Same textual scheme as moodle.py and moodle_browser.py (SQLite history keeps working).
        for source in ('moodle.py', 'moodle_browser.py'):
            self.assertIn("moodle:course:{", (ROOT / 'campus_ai' / source).read_text(encoding='utf-8'))

    def test_fingerprints_do_not_change_between_reads(self):
        first = {i.uid: i.fingerprint() for i in contract.to_academic_items(self.snapshot)}
        later = copy.deepcopy(self.result['snapshot'])
        later['generated_at'] = '2026-11-09T08:30:00Z'
        for table in ('courses', 'sections', 'materials', 'activities'):
            for record in later[table]:
                record['provenance']['observed_at'] = '2026-11-09T08:30:00Z'
        again = {i.uid: i.fingerprint() for i in contract.to_academic_items(contract.parse_snapshot(later))}
        self.assertEqual(first, again)
        self.assertEqual(len(first), 7)

    def test_nothing_is_claimed_about_delivery_or_deadlines(self):
        now = contract._parse_aware(self.snapshot.generated_at)
        for activity in self.snapshot.activities:
            self.assertEqual(contract.pending_state(activity, now=now), 'desconhecido')
            self.assertEqual(activity.deadlines, ())
        for item in contract.to_academic_items(self.snapshot):
            self.assertEqual((item.status, item.due_iso), ('unknown', ''))

    def test_only_real_assignments_become_assignments(self):
        categories = {i.uid.rsplit(':', 1)[1]: i.category for i in contract.to_academic_items(self.snapshot)}
        self.assertEqual({k for k, v in categories.items() if v == 'assignment'},
                         {'90001', '90002', '90003', '90005', '90007'})
        self.assertEqual(categories['90004'], 'material')     # resource_pdf
        self.assertEqual(categories['90006'], 'material')     # groupselect is not "work to do"

    def test_av_groups_survive_the_round_trip(self):
        groups = {r.uid.rsplit(':', 1)[1]: (r.assessment, r.assessment_basis)
                  for r in (*self.snapshot.materials, *self.snapshot.activities)}
        self.assertEqual(groups['90004'], ('AV1', 'titulo'))
        self.assertEqual(groups['90001'], ('AV1', 'posicao'))
        self.assertEqual(groups['90007'], ('AV2', 'posicao'))

    def test_host_accepts_exactly_what_background_js_sends(self):
        received = []
        session = cp.CompanionSession({'7653'}, received.append, token_factory=lambda: TOKEN)
        replies = [session.handle(json.dumps(m).encode('utf-8')) for m in self.lines[1:]]
        self.assertEqual([r['type'] for r in replies], ['welcome', 'ack'], replies)
        self.assertEqual(replies[1]['counts'], {'materials': 1, 'activities': 6})
        self.assertEqual(received[0], self.snapshot)

    def test_host_still_enforces_the_authorized_course_list(self):
        session = cp.CompanionSession({'1'}, lambda s: self.fail('must not be delivered'), token_factory=lambda: TOKEN)
        replies = [session.handle(json.dumps(m).encode('utf-8')) for m in self.lines[1:]]
        self.assertEqual(replies[1]['code'], 'disciplina_nao_autorizada')

    def test_unconfirmed_pages_produce_no_report(self):
        for override, code in (({'formatTiles': False}, 'formato_nao_suportado'),
                               ({'courseId': ''}, 'identidade_nao_confirmada'),
                               ({'sectionId': ''}, 'secao_sem_id')):
            lines = emit({**golden(), **override}, self.tmp.name)
            self.assertEqual(lines[0], {'ok': False, 'code': code})
            self.assertEqual(len(lines), 2, 'only hello may be built when the adapter refuses')

    def test_page_report_is_refused_for_a_non_reportable_page(self):
        with self.assertRaises(AssertionError):
            emit(golden(), self.tmp.name, url='https://ead.aedb.br/ava/mod/assign/view.php?id=90001')

    def test_kind_vocabularies_equal_the_contract(self):
        js = (EXT / 'src' / 'tiles_adapter.js').read_text(encoding='utf-8')
        for name, expected in (('MATERIAL_KINDS', contract.MATERIAL_KINDS), ('ACTIVITY_KINDS', contract.ACTIVITY_KINDS)):
            block = re.search(rf'export const {name} = new Set\(\[(.*?)\]\)', js, re.S).group(1)
            self.assertEqual(set(re.findall(r"'([a-z0-9]+)'", block)), set(expected), name)


