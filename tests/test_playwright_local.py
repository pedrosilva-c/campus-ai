"""Opt-in local browser smoke test. Never visits an external URL."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.environ.get('CAMPUS_AI_BROWSER_SMOKE') == '1',
                     'Execute explicitamente com CAMPUS_AI_BROWSER_SMOKE=1')
class PlaywrightLocalTests(unittest.TestCase):
    def test_ui_and_playwright_import(self):
        import campus_ai.ui
        from playwright.sync_api import sync_playwright
        self.assertTrue(callable(sync_playwright))

    def test_persistent_chromium_opens_about_blank(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / 'browser_profile'
            code = '''from playwright.sync_api import sync_playwright
import sys
print('driver: starting', flush=True)
with sync_playwright() as playwright:
    print('driver: ready', flush=True)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=sys.argv[1], headless=False, accept_downloads=False)
    try:
        print('chromium: ready', flush=True)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto('about:blank')
        assert page.url == 'about:blank'
        print('about:blank: OK', flush=True)
    finally:
        context.close()
'''
            env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH='0')
            try:
                result = subprocess.run([sys.executable, '-c', code, str(profile)],
                                        capture_output=True, text=True, timeout=20, env=env)
            except subprocess.TimeoutExpired as exc:
                output = (exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
                self.fail('Inicialização local excedeu 20 s: ' + output.strip())
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('about:blank: OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
