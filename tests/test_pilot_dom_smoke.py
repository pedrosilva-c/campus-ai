"""Opt-in actual DOM/download policy test: about:blank, synthetic HTML, temp profile."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                     'Chromium local opt-in: CAMPUS_AI_BROWSER_SMOKE=1')
class PilotDOMSmoke(unittest.TestCase):
    def test_fixture_visible_titles_due_and_download_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            code = r'''
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError
from campus_ai.pilot import SNAPSHOT_JS, resolve_title
with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(sys.argv[1], headless=False, accept_downloads=False)
    try:
        context.route('**/*', lambda route: route.abort())
        page = context.pages[0]
        page.goto('about:blank')
        cdp = context.new_cdp_session(page)
        cdp.send('Browser.setDownloadBehavior', {'behavior': 'deny'})
        page.set_content(Path('tests/fixtures/pilot_course.html').read_text(encoding='utf-8'))
        result = page.evaluate(SNAPSHOT_JS, {'max_elements': 3000, 'timeout_ms': 5000, 'selection_only': False})
        found = resolve_title(result['title_candidates'], result['doc_title'])
        assert found and found.title == 'Disciplina fictícia', result['title_candidates']
        assert len(result['rows']) == 3, result['rows']
        assert result['rows'][1]['due'] == ''
        assert result['rows'][2]['due'] == 'Vencimento: 20/10/2026, 23:59'
        assert 'Oculto' not in str(result['rows'])
        selection = page.evaluate(SNAPSHOT_JS, {'max_elements': 3000, 'timeout_ms': 5000, 'selection_only': True})
        assert selection['rows'] == []
        # A synthetic blob, never a Moodle file. Chromium must not save it.
        try:
            with page.expect_download(timeout=1500) as download:
                page.evaluate("""() => {
                    const a = document.createElement('a');
                    a.href = URL.createObjectURL(new Blob(['synthetic fixture']));
                    a.download = 'pilot-fixture.txt'; a.click();
                }""")
            assert download.value.failure() is not None
        except TimeoutError:
            pass  # Chromium may reject before emitting a Playwright download event.
        assert not list(Path(sys.argv[1]).rglob('pilot-fixture.txt'))
        assert page.url == 'about:blank'
        print('pilot DOM and download policy: OK')
    finally:
        context.close()
'''
            result = subprocess.run([sys.executable, '-c', code, directory], capture_output=True,
                                    text=True, timeout=25, env=dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0'))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('pilot DOM and download policy: OK', result.stdout)
