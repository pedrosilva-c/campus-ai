import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from campus_ai.cli import main
from campus_ai.config import Settings
from campus_ai.moodle import MoodleAccess


class MoodleCheckCliTests(unittest.TestCase):
    def test_local_browser_check_never_scans_aedb(self):
        output = io.StringIO()
        with patch('sys.argv', ['campus-ai', '--check-browser-local']), \
             patch('campus_ai.config.Settings.load', return_value=Settings()), \
             patch('campus_ai.moodle_browser.MoodleBrowserClient') as client, \
             redirect_stdout(output):
            client.return_value.smoke_local.return_value = True
            code = main()
        self.assertEqual(code, 0)
        self.assertIn('OK', output.getvalue())
        client.return_value.scan.assert_not_called()
        client.return_value.connect.assert_not_called()

    def test_check_moodle_without_token_does_not_connect(self):
        output = io.StringIO()
        with patch('sys.argv', ['campus-ai', '--check-moodle']), \
             patch('campus_ai.config.Settings.load', return_value=Settings()), \
             patch('campus_ai.security.get_secret', return_value=None), \
             patch('campus_ai.moodle.MoodleClient') as client, \
             redirect_stdout(output):
            code = main()
        self.assertEqual(code, 1)
        self.assertIn('Token Moodle', output.getvalue())
        client.assert_not_called()

    def test_check_moodle_reports_declared_functions_without_secrets(self):
        output = io.StringIO()
        access = MoodleAccess(7, ('core_enrol_get_users_courses',),
                              ('core_course_get_contents',), False)
        with patch('sys.argv', ['campus-ai', '--check-moodle']), \
             patch('campus_ai.config.Settings.load', return_value=Settings()), \
             patch('campus_ai.security.get_secret', return_value='fake-token'), \
             patch('campus_ai.moodle.MoodleClient') as client, \
             redirect_stdout(output):
            client.return_value.probe.return_value = access
            code = main()
        self.assertEqual(code, 0)
        self.assertIn('core_course_get_contents', output.getvalue())
        self.assertNotIn('fake-token', output.getvalue())
        client.return_value.scan.assert_not_called()


if __name__ == '__main__':
    unittest.main()
