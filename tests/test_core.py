import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from campus_ai.config import Settings
from campus_ai.engine import run_scan
from campus_ai.models import AcademicItem
from campus_ai.state import History
from campus_ai.obsidian import ObsidianWriter, NoteModifiedError, safe_link
from campus_ai.demo import sample_items


class CampusCoreTests(unittest.TestCase):
    def test_history_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            h = History(Path(directory) / 'state.db')
            item = AcademicItem('1', 'demo', 'material', 'Título')
            self.assertTrue(h.changed(item))
            h.remember(item)
            self.assertFalse(h.changed(item))
            item.title = 'Alteração'
            self.assertTrue(h.changed(item))

    def test_write_obsidian(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = ObsidianWriter(directory)
            first = sample_items()[0]
            p = writer.sync_item(first)
            self.assertTrue(p.exists())
            self.assertIn('Exercício: consultas SQL', p.read_text(encoding='utf8'))
            self.assertEqual(writer.filename_for(first), p)
            writer.dashboard(sample_items(), [])
            dash = Path(directory) / 'Campus AI' / 'Painel Acadêmico.md'
            self.assertIn('Banco de Dados', dash.read_text(encoding='utf8'))

    def test_no_file_urls(self):
        self.assertEqual(safe_link('file:///tmp/x'), '')
        self.assertEqual(safe_link('javascript:alert(1)'), '')
        self.assertEqual(safe_link('https://ead.aedb.br/ava'), 'https://ead.aedb.br/ava')

    def test_existing_personal_note_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = ObsidianWriter(directory)
            item = sample_items()[0]
            path = writer.filename_for(item)
            path.parent.mkdir(parents=True)
            path.write_text('Minha nota pessoal', encoding='utf8')
            with self.assertRaises(NoteModifiedError):
                writer.sync_item(item)
            self.assertEqual(path.read_text(encoding='utf8'), 'Minha nota pessoal')

    def test_edited_generated_note_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = ObsidianWriter(directory)
            item = sample_items()[0]
            path = writer.sync_item(item)
            path.write_text(path.read_text(encoding='utf8') + '\nMinha anotação', encoding='utf8')
            item.description = 'Conteúdo novo do Moodle'
            with self.assertRaises(NoteModifiedError):
                writer.sync_item(item)
            self.assertIn('Minha anotação', path.read_text(encoding='utf8'))

    def test_edited_dashboard_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = ObsidianWriter(directory)
            path = writer.root / 'Painel Acadêmico.md'
            writer.dashboard(sample_items(), [])
            path.write_text(path.read_text(encoding='utf8') + '\nMinha anotação', encoding='utf8')
            with self.assertRaises(NoteModifiedError):
                writer.dashboard([], ['Falha de conector'])
            self.assertIn('Minha anotação', path.read_text(encoding='utf8'))

    def test_renamed_activity_keeps_its_note_path(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = ObsidianWriter(directory)
            item = sample_items()[0]
            original = writer.sync_item(item)
            item.title = 'Novo nome da atividade'
            self.assertEqual(writer.sync_item(item), original)
            self.assertIn('Novo nome da atividade', original.read_text(encoding='utf8'))
            self.assertEqual(len(list(original.parent.glob('*.md'))), 1)

    def test_sync_preserves_manual_edits_and_does_not_acknowledge_failed_write(self):
        with tempfile.TemporaryDirectory() as directory:
            item = sample_items()[0]
            settings = Settings(mode='demo', vault_path=directory)
            with patch('campus_ai.engine.app_dir', return_value=Path(directory)), \
                 patch('campus_ai.engine.sample_items', return_value=[item]):
                first = run_scan(settings)
                self.assertEqual(len(first.new_items), 1)
                path = ObsidianWriter(directory).filename_for(item)
                path.write_text(path.read_text(encoding='utf8') + '\nMeu comentário', encoding='utf8')
                item.description = 'Novo texto da fonte'
                second = run_scan(settings)
                self.assertEqual(second.new_items, [])
                self.assertTrue(any('nota existente foi preservada' in w for w in second.warnings))
                self.assertIn('Meu comentário', path.read_text(encoding='utf8'))
                self.assertTrue(History(Path(directory) / 'demo.db').changed(item))


if __name__ == '__main__':
    unittest.main()
