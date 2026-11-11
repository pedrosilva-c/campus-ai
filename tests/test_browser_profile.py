import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock

from campus_ai.browser_profile import BrowserProfileUnsafe, verify_private_profile
from campus_ai.moodle_browser import MoodleBrowserClient


class ProfileSafetyTests(unittest.TestCase):
    def test_verification_uses_read_only_acl_command_without_exposing_output(self):
        with patch('campus_ai.browser_profile.subprocess.run', return_value=Mock(returncode=0)) as run:
            verify_private_profile()
        args = run.call_args.args[0]
        self.assertIn('-Command', args)
        command = args[args.index('-Command') + 1]
        self.assertIn('Get-Acl', command)
        self.assertIn('browser_profile', command)
        self.assertTrue(run.call_args.kwargs['capture_output'])


    def test_verification_checks_parent_and_profile_acl(self):
        with patch('campus_ai.browser_profile.subprocess.run', return_value=Mock(returncode=0)) as run:
            verify_private_profile()
        command = run.call_args.args[0][-1]
        self.assertIn('foreach ($path in @($root, $profile))', command)
        self.assertIn('Get-Acl -LiteralPath $path', command)
        self.assertIn('AreAccessRulesProtected', command)
        self.assertIn('FullControl', command)
        self.assertNotIn('Set-Acl', command)

    def test_parent_acl_failure_blocks_connection_before_playwright(self):
        result = Mock(returncode=1, stdout='', stderr='')
        with tempfile.TemporaryDirectory() as directory:
            with patch('campus_ai.moodle_browser.app_dir', return_value=Path(directory)), \
                 patch('campus_ai.browser_profile.subprocess.run', return_value=result):
                client = MoodleBrowserClient('https://ead.aedb.br/ava')
                with self.assertRaises(BrowserProfileUnsafe):
                    client.smoke_local()

    def test_verified_parent_and_profile_allow_playwright_launch(self):
        page = Mock(url='about:blank')
        browser = Mock(pages=[page])
        driver = Mock()
        driver.chromium.launch_persistent_context.return_value = browser
        manager = MagicMock()
        manager.__enter__ = Mock(return_value=driver)
        manager.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as directory:
            with patch('campus_ai.moodle_browser.app_dir', return_value=Path(directory)), \
                 patch('campus_ai.moodle_browser.verify_private_profile') as verify, \
                 patch('playwright.sync_api.sync_playwright', return_value=manager):
                client = MoodleBrowserClient('https://ead.aedb.br/ava')
                self.assertTrue(client.smoke_local())
        verify.assert_called_once_with()
        driver.chromium.launch_persistent_context.assert_called_once()
        page.goto.assert_called_once_with('about:blank', wait_until='domcontentloaded', timeout=15000)

    def test_prepare_script_backs_up_both_acls_before_target_change(self):
        script = (Path(__file__).resolve().parents[1] / 'scripts' /
                  'preparar_perfil_moodle_windows.ps1').read_text(encoding='utf-8')
        prepare = script.split('if ($Prepare) {', 1)[1].split('} elseif ($Restore) {', 1)[0]
        self.assertIn('rootSddl = (Get-Acl -LiteralPath $root).Sddl', prepare)
        self.assertIn('profileSddl = (Get-Acl -LiteralPath $profile).Sddl', prepare)
        self.assertLess(prepare.index('FileMode]::CreateNew'), prepare.index('Set-PrivateAcl $root'))
        self.assertLess(prepare.index('Assert-PrivateAcl $backup'), prepare.index('Set-PrivateAcl $root'))
        self.assertIn('Set-PrivateAcl $profile', prepare)
        self.assertIn('ProtectedData]::Protect', prepare)
        self.assertIn('ProtectedData]::Unprotect', script)
        self.assertIn('SetSecurityDescriptorSddlForm($saved.rootSddl)', script)
        self.assertIn('SetSecurityDescriptorSddlForm($saved.profileSddl)', script)

    def test_prepare_script_rejects_unrecognized_parent_entries(self):
        script = (Path(__file__).resolve().parents[1] / 'scripts' /
                  'preparar_perfil_moodle_windows.ps1').read_text(encoding='utf-8')
        self.assertIn('Assert-Inventory $root', script)
        self.assertIn('Get-ChildItem -LiteralPath $Root -Force', script)
        self.assertIn("'browser_profile' = 'Directory'", script)
        self.assertIn('Pasta CampusAI contém entrada não reconhecida.', script)

    def test_unsafe_acl_blocks_connection_before_playwright(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('campus_ai.moodle_browser.app_dir', return_value=root), \
                 patch('campus_ai.moodle_browser.verify_private_profile',
                       side_effect=BrowserProfileUnsafe('Perfil não seguro')):
                client = MoodleBrowserClient('https://ead.aedb.br/ava')
                with self.assertRaises(BrowserProfileUnsafe):
                    client.check_session()

    def test_failed_acl_check_does_not_show_command_output(self):
        result = Mock(returncode=1, stdout='private cookie', stderr='private token')
        with patch('campus_ai.browser_profile.subprocess.run', return_value=result):
            with self.assertRaises(BrowserProfileUnsafe) as raised:
                verify_private_profile()
        self.assertNotIn('private cookie', str(raised.exception))
        self.assertNotIn('private token', str(raised.exception))

    def test_local_persistent_smoke_uses_only_about_blank(self):
        page = Mock(url='about:blank')
        client = MoodleBrowserClient('https://ead.aedb.br/ava', page=page)
        self.assertTrue(client.smoke_local())
        page.goto.assert_called_once_with('about:blank', wait_until='domcontentloaded', timeout=15000)
