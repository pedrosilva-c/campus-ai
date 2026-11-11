"""POC structure probe (docs/poc/structure_probe.js) against fictitious fixtures in local Chromium.

Opt-in like the other DOM tests (CAMPUS_AI_BROWSER_SMOKE=1): every network request is aborted and only
synthetic HTML is loaded with set_content. The static part runs always.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / 'docs' / 'poc' / 'structure_probe.js'


class ProbeStaticTests(unittest.TestCase):
    def test_probe_is_read_only(self):
        code = PROBE.read_text(encoding='utf-8')
        for pattern in (r'\.click\s*\(', r'\.submit\s*\(', r'\bfetch\s*\(', r'XMLHttpRequest', r'location\.(assign|replace|href\s*=)',
                        r'document\.cookie', r'localStorage', r'sessionStorage', r'\beval\s*\(', r'innerHTML\s*=',
                        r'scroll(To|By|IntoView)', r'dispatchEvent', r'window\.open'):
            self.assertIsNone(re.search(pattern, code), pattern)


@unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                     'Chromium local opt-in: CAMPUS_AI_BROWSER_SMOKE=1')
class ProbeChromiumTests(unittest.TestCase):
    def run_probe(self, fixture, calls):
        code = r'''
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright
probe = Path(sys.argv[2]).read_text(encoding='utf-8')
html = Path(sys.argv[3]).read_text(encoding='utf-8')
calls = json.loads(sys.argv[4])
with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(sys.argv[1], headless=True, accept_downloads=False)
    try:
        context.route('**/*', lambda route: route.abort())
        page = context.pages[0]
        page.goto('about:blank')
        page.set_content(html)
        page.evaluate("window.__clicks = []")
        out = [page.evaluate(probe, options) for options in calls]
        out.append(page.evaluate("window.__clicks"))
        print(json.dumps(out))
    finally:
        context.close()
'''
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp-campus-ai') as directory:
            proc = subprocess.run([sys.executable, '-c', code, directory, str(PROBE),
                                   str(ROOT / 'tests' / 'fixtures' / fixture), json.dumps(calls)],
                                  capture_output=True, text=True, encoding='utf-8', timeout=60, cwd=ROOT,
                                  env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0'))
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_structure_mode_leaks_no_page_text(self):
        structure, clicks = self.run_probe('cards_course.html', [{'mode': 'structure', 'courseId': '42'}])
        self.assertEqual(clicks, [])
        labels = {c['label'] for c in structure['cards']}
        self.assertIn('atividades avaliativas', labels)
        self.assertIn('trilhas de aprendizagem', labels)
        self.assertTrue(structure['pageCarriesCourseId'])
        dumped = json.dumps(structure, ensure_ascii=False)
        for private in ('Estudante', 'Texto informativo', 'lattes.example', 'Modelagem Fictícia', '901'):
            self.assertNotIn(private, dumped)
        for card in structure['cards']:
            self.assertNotRegex(card['linkRoute'], r'[0-9]')

    def test_av_mode_requires_consent_and_reads_av_sections(self):
        refused, consented, clicks = self.run_probe('nav_avaliativas.html', [{'mode': 'av'},
                                                                             {'mode': 'av', 'consent': True}])
        self.assertEqual(refused['error'], 'consentimento_ausente')
        self.assertEqual(clicks, [])
        av1 = next(s for s in consented['sections'] if s['section'] == 'AV1')
        work = next(i for i in av1['items'] if i['type'] == 'assign')
        self.assertEqual(work['title'], 'Trabalho AV1 fictício')
        self.assertEqual(work['cmid'], '22')
        self.assertTrue(any('20 out 2026' in d for d in work['dates']))
        self.assertTrue(work['hidden'])   # collapsed section: read from the DOM without expanding it


if __name__ == '__main__':
    unittest.main()
