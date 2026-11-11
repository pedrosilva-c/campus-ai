"""Last test module: the student's real data, registry value and host files must be exactly as before the run."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _isolation  # noqa: E402


class RealDataUntouchedTests(unittest.TestCase):
    def test_nothing_real_changed_during_the_run(self):
        recorded = _isolation.recorded_signature()
        if recorded is None:
            self.skipTest('isolamento não instalado neste processo (módulo executado isoladamente)')
        now = json.loads(json.dumps(_isolation.real_signature(), sort_keys=True))
        changed = sorted(key for key in set(recorded) | set(now) if recorded.get(key) != now.get(key))
        self.assertEqual(changed, [], 'dados REAIS mudaram durante a execução dos testes (ou o Campus AI/Chrome '
                                     f'gravou ao mesmo tempo): {changed}')


if __name__ == '__main__':
    unittest.main()
