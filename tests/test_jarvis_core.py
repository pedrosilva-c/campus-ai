"""Jarvis core (stage 1): understanding, tools on real-shaped local data, memory, reminders, documents, panel.

FICTITIOUS data, temporary folders and databases only. The clock is fixed: 10/11/2026 12:00 UTC (09:00 in São Paulo).
"""
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companion_snapshots import snapshot_dict  # noqa: E402
from test_companion_deadlines import CHECKED, VARIETY, with_details  # noqa: E402

from campus_ai import companion_store as cs  # noqa: E402
from campus_ai import contract  # noqa: E402
from campus_ai.jarvis import Jarvis, JarvisStore, documents, nlu  # noqa: E402
from campus_ai.jarvis.store import looks_secret  # noqa: E402

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
BRT = timezone(timedelta(hours=-3))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.live = self.dir / 'live.db'
        self.out = self.dir / 'entregas'

    def with_reading(self, per_cmid=VARIETY):
        store = cs.SnapshotStore(self.live, allowed_courses=['7653'])
        store.save(contract.parse_snapshot(with_details(snapshot_dict(generated=CHECKED), per_cmid)), received_at=CHECKED)

    def jarvis(self, clock=NOW):
        self.store = JarvisStore(self.dir / 'jarvis.db')
        return Jarvis(self.store, live_db=self.live, output_dir=self.out, clock=lambda: clock)


class UnderstandingTests(unittest.TestCase):
    def test_the_examples_of_the_request_reach_a_real_tool(self):
        cases = {
            'Jarvis, o que tenho para fazer hoje?': 'hoje', 'Jarvis, preciso resolver minhas atividades de hoje.': 'hoje',
            'Quais atividades vencem primeiro?': 'proximos_prazos', 'Quais tarefas ainda não entreguei?': 'nao_entregues',
            'O que está atrasado?': 'atrasadas', 'O que já entreguei?': 'entregues',
            'Existe alguma atividade atrasada?': 'atrasadas', 'Jarvis, o que tenho para fazer?': 'pendencias',
            'Organize minha semana de acordo com os prazos.': 'planejar_semana',
            'Identifique a atividade mais urgente e prepare um documento para mim.': 'preparar_atividade',
            'Explique o que está pendente e o que já foi concluído.': 'panorama',
            'o que já foi entregue?': 'entregues', 'anota aí que o professor aceita entrega em PDF': 'memoria_adicionar',
            'tem algo que eu esqueci de mandar?': 'nao_suportado',          # weak: the local model may re-read it
            'o que eu disse sobre a AV2?': 'buscar_conversa',
            'Prepare minha atividade de Modelagem UML.': 'preparar_atividade', 'Prepare essa atividade para mim.': 'preparar_atividade',
            'Organize minha semana.': 'planejar_semana', 'Me avise amanhã sobre essa entrega': 'lembrete_criar',
            'Faça um resumo dessa matéria.': 'nao_suportado', 'Pesquise sobre esse assunto e prepare um documento.': 'nao_suportado',   # no web search yet: refuse
            'me lembre de enviar o relatório amanhã às 18h': 'lembrete_criar',
            'lembre que preciso enviar a AV2 em grupo': 'memoria_adicionar',
            'Abra meu projeto Campus AI e verifique o que falta.': 'nao_suportado',
            'lembre que eu prefiro estudar à noite': 'memoria_adicionar', 'O que você sabe sobre mim?': 'memoria_listar',
            'apague a memória 3': 'memoria_apagar', 'corrija a memória 2 para estudo de manhã': 'memoria_corrigir',
            'quais são meus lembretes': 'lembrete_listar', 'cancele o lembrete 4': 'lembrete_cancelar',
            'sim': 'confirmar', 'não': 'cancelar_pendente', 'a segunda': 'escolher', '3': 'escolher',
            'o que está conectado?': 'integracoes', 'ajuda': 'ajuda', 'envie um e-mail ao professor': 'recusar_acao',
            'submeta a tarefa': 'recusar_acao', 'inicie o questionário': 'recusar_acao',
            'qual a capital da França?': 'desconhecido',
        }
        for text, expected in cases.items():
            self.assertEqual(nlu.parse(text).name, expected, text)

    def test_slots_keep_the_students_words(self):
        intent = nlu.parse('Jarvis, lembre que a AV2 é em grupo com a Ana')
        self.assertEqual(intent.slots['texto'], 'a AV2 é em grupo com a Ana')
        self.assertEqual(nlu.parse('a segunda').slots['indice'], 2)
        self.assertEqual(nlu.parse('a última').slots['indice'], -1)

    def test_time_expressions(self):
        now = datetime(2026, 11, 10, 9, 0, tzinfo=BRT)                       # a Tuesday
        cases = {
            'me avise amanhã': datetime(2026, 11, 11, 9, 0, tzinfo=BRT),
            'me avise amanhã às 18h': datetime(2026, 11, 11, 18, 0, tzinfo=BRT),
            'me lembre hoje às 20:30': datetime(2026, 11, 10, 20, 30, tzinfo=BRT),
            'me avise daqui a 2 horas': now + timedelta(hours=2),
            'me avise em 30 minutos': now + timedelta(minutes=30),
            'me avise na sexta às 7h': datetime(2026, 11, 13, 7, 0, tzinfo=BRT),
            'me avise dia 15 às 8h': datetime(2026, 11, 15, 8, 0, tzinfo=BRT),
            'me avise às 8h': datetime(2026, 11, 11, 8, 0, tzinfo=BRT),        # 08:00 already passed: tomorrow
            'me avise às 7 da noite': datetime(2026, 11, 10, 19, 0, tzinfo=BRT),
        }
        for text, expected in cases.items():
            self.assertEqual(nlu.parse_when(nlu.fold(text), now), expected, text)
        due = datetime(2026, 11, 12, 23, 59, tzinfo=BRT)
        self.assertEqual(nlu.parse_when('me avise um dia antes do prazo', now, due), due - timedelta(days=1))
        self.assertEqual(nlu.parse_when('2 horas antes', now, due), due - timedelta(hours=2))
        self.assertIsNone(nlu.parse_when('um dia antes do prazo', now, None))     # no deadline known: no guess
        self.assertIsNone(nlu.parse_when('me avise', now))
        self.assertIsNone(nlu.parse_when('hoje às 7h', now))                       # already passed


class StoreTests(Base):
    def test_secrets_are_never_stored(self):
        store = JarvisStore(self.dir / 'jarvis.db')
        for secret in ('minha senha é 1234', 'o token do moodle é x', 'cookie MoodleSession=abc',
                       'chave de api sk-ant-0123456789abcdefghijklmnopqrstuvwxyz', '4111111111111111'):
            self.assertTrue(looks_secret(secret), secret)
            with self.assertRaises(Exception):
                store.remember(secret)
        store.add_message('user', 'minha senha é 1234')
        self.assertNotIn('1234', store.messages()[-1]['text'])
        self.assertFalse(looks_secret('A AV2 vale 4 pontos e é em grupo'))
        self.assertFalse(looks_secret('https://ead.aedb.br/ava/mod/assign/view.php?id=90001'))

    def test_operations_left_running_are_marked_failed_after_a_crash(self):
        store = JarvisStore(self.dir / 'jarvis.db')
        op = store.start_operation('preparar_atividade', {'texto': 'x'})
        self.assertEqual(store.recover_interrupted(), 1)
        self.assertEqual(store.operations()[0]['status'], 'falhou')
        self.assertEqual(store.operations()[0]['id'], op)


class AcademicTests(Base):
    def test_today_answers_from_the_saved_reading_and_says_how_each_fact_is_known(self):
        self.with_reading()
        reply = self.jarvis().handle('Jarvis, o que tenho para fazer hoje?')
        self.assertEqual(reply.status, 'ok')
        self.assertIn('Atrasadas:', reply.text)
        self.assertIn('Tarefa em grupo sintética — 01/11/2026 23:59', reply.text)
        self.assertIn('Nos próximos 7 dias:', reply.text)
        self.assertIn('Exercício sintético C — 11/11/2026 23:59', reply.text)
        self.assertNotIn('Exercício sintético B', reply.text)                     # submitted: not "to do"
        self.assertIn('Cobertura parcial', reply.text)
        self.assertIn('Aguardando avaliação: 1 • Concluídas: 1', reply.text)

    def test_never_invents_when_nothing_was_verified_or_read(self):
        reply = self.jarvis().handle('o que tenho para fazer hoje?')               # no live.db at all
        self.assertEqual(reply.status, 'falhou')
        self.assertIn('não vou inventar', reply.text)
        self.with_reading(per_cmid={})                                              # a reading without details
        reply = self.jarvis().handle('o que tenho para fazer hoje?')
        self.assertIn('nenhuma página de atividade foi verificada', reply.text)
        self.assertIn('isso não quer dizer que estejam em dia', reply.text)
        self.assertNotIn('Nenhuma pendência comprovada', reply.text)

    def test_next_deadlines_and_not_delivered(self):
        self.with_reading()
        j = self.jarvis()
        nxt = j.handle('Quais atividades vencem primeiro?').text
        self.assertLess(nxt.index('Exercício sintético C'), nxt.index('Exercício sintético A'))
        self.assertNotIn('Tarefa em grupo sintética', nxt)                         # past: not "next"
        pending = j.handle('Quais tarefas ainda não entreguei?').text
        for title in ('Tarefa em grupo sintética', 'Exercício sintético C', 'Exercício sintético A'):
            self.assertIn(title, pending)
        self.assertNotIn('AV1 - Correção sintética', pending)                      # graded


class PrepareTests(Base):
    def test_prepare_that_activity_delivers_a_word_and_a_markdown_file(self):
        self.with_reading()
        j = self.jarvis()
        j.handle('o que tenho para fazer hoje?')
        reply = j.handle('Prepare essa atividade para mim.')
        self.assertEqual(reply.status, 'ok')
        self.assertEqual(len(reply.files), 2)
        docx, md = map(Path, reply.files)
        self.assertEqual((docx.suffix, md.suffix), ('.docx', '.md'))
        self.assertTrue(str(docx).startswith(str(self.out)))
        with zipfile.ZipFile(docx) as z:
            self.assertLessEqual({'[Content_Types].xml', '_rels/.rels', 'word/document.xml', 'word/styles.xml'}, set(z.namelist()))
            body = z.read('word/document.xml').decode('utf-8')
            ElementTree.fromstring(body)                                           # well-formed XML
            for part in z.namelist():
                if part.endswith('.xml') or part.endswith('.rels'):
                    ElementTree.fromstring(z.read(part))
        text = md.read_text(encoding='utf-8')
        self.assertIn('# Preparação — Tarefa em grupo sintética', text)           # the most urgent one (late)
        self.assertIn('confirmado na página da atividade', text)
        self.assertIn('O prazo já passou', text)
        self.assertIn('o Campus AI não lê o texto das atividades', text)
        self.assertIn('nunca envia, submete ou inicia tentativas', text)
        self.assertIn('Tarefa em grupo sintética', body)

    def test_a_named_course_with_several_activities_asks_which_and_a_number_answers(self):
        self.with_reading()
        j = self.jarvis()
        ask = j.handle('Prepare minha atividade de disciplina fictícia')
        self.assertEqual(ask.status, 'aguardando_confirmacao')
        self.assertIn('Qual atividade? Responda com o número', ask.text)
        self.assertEqual(ask.files, [])
        first_line = ask.text.splitlines()[1]
        reply = j.handle('1')
        self.assertEqual(len(reply.files), 2)
        self.assertIn(first_line.split('. ', 1)[1].split(' — ')[0], Path(reply.files[1]).read_text(encoding='utf-8'))

    def test_a_name_is_matched_by_whole_words(self):
        from campus_ai.jarvis import academic
        self.with_reading()
        snap = academic.load(self.live, NOW)
        for text, expected in (('bora montar um material pro trabalho do grupo', ['Tarefa em grupo sintética']),
                               ('prepare a correção sintética', ['AV1 - Correção sintética'])):
            self.assertEqual([a.title for a in academic.find(snap, text)], expected, text)
        # Only a single letter tells them apart: single letters are articles in Portuguese ("a", "o") and are not
        # used, so all three stay candidates and the agent asks which one (never a guess).
        self.assertEqual(len(academic.find(snap, 'prepare o exercicio sintetico c')), 3)

    def test_files_never_overwrite_an_existing_one(self):
        doc = documents.Document('Teste')
        a = documents.write(doc, self.out, 'mesmo-nome')
        b = documents.write(doc, self.out, 'mesmo-nome')
        self.assertEqual(len({*a, *b}), 4)

    def test_week_plan(self):
        self.with_reading()
        reply = self.jarvis().handle('Organize minha semana')
        self.assertEqual(len(reply.files), 2)
        text = Path(reply.files[1]).read_text(encoding='utf-8')
        self.assertIn('Exercício sintético C (prazo 23:59)', text)
        self.assertIn('1 atrasada', reply.text)


class ConversationTests(Base):
    def test_reminders_are_created_from_context_and_become_due(self):
        self.with_reading()
        j = self.jarvis()
        j.handle('Quais atividades vencem primeiro?')                             # focus: Exercício sintético C
        reply = j.handle('Me avise um dia antes do prazo dessa entrega')
        self.assertIn('Exercício sintético C — prazo 11/11/2026 23:59', reply.text)
        (reminder,) = self.store.pending_reminders()
        self.assertEqual(datetime.fromisoformat(reminder.due_at), datetime(2026, 11, 11, 2, 59, tzinfo=timezone.utc))
        self.assertEqual(self.store.due_reminders(NOW), [])
        self.assertEqual(len(self.store.due_reminders(NOW + timedelta(hours=15))), 1)
        self.assertIn('nº', j.handle('quais são meus lembretes').text)
        self.assertIn('cancelado', j.handle(f'cancele o lembrete {reminder.id}').text)
        self.assertEqual(self.store.pending_reminders(), [])
        self.assertEqual(j.handle('me avise sobre isso').status, 'falhou')         # no time: asks, nothing stored

    def test_memory_can_be_kept_listed_corrected_and_deleted_with_confirmation(self):
        j = self.jarvis()
        self.assertIn('nº 1, preferencia', j.handle('lembre que eu prefiro estudar à noite').text)
        self.assertIn('eu prefiro estudar à noite', j.handle('o que você sabe sobre mim?').text)
        self.assertIn('corrigida', j.handle('corrija a memória 1 para eu prefiro estudar de manhã').text)
        ask = j.handle('apague a memória 1')
        self.assertEqual(ask.status, 'aguardando_confirmacao')
        self.assertIsNotNone(self.store.memory(1))                                # nothing deleted yet
        self.assertIn('não fiz nada', j.handle('não').text)
        self.assertIsNotNone(self.store.memory(1))
        j.handle('apague a memória 1')
        j.handle('o que tenho para fazer hoje?')                                  # another request drops the question
        self.assertIn('Não há nada aguardando', j.handle('sim').text)
        self.assertIsNotNone(self.store.memory(1))
        j.handle('apague a memória 1')
        self.assertIn('apagada', j.handle('sim').text)
        self.assertIsNone(self.store.memory(1))
        j.handle('lembre que a AV2 é em grupo com 3 pessoas')
        found = j.handle('o que eu disse sobre a AV2?')                           # punctuation must not break it
        self.assertIn('a AV2 é em grupo com 3 pessoas', found.text)
        self.assertEqual(j.handle('o que eu disse sobre o churrasco?').status, 'falhou')
        for memory in self.store.memories():
            self.store.forget(memory.id)
        refused = j.handle('lembre que minha senha do moodle é 123')
        self.assertEqual(refused.status, 'recusado')
        self.assertEqual(self.store.memories(), [])

    def test_external_actions_are_refused_and_unknown_requests_are_not_guessed(self):
        j = self.jarvis()
        for text, reason in (('Faça um resumo dessa matéria', 'modelo de linguagem'),
                             ('envie um e-mail para o professor', 'não é algo que eu faça por você'),
                             ('submeta a tarefa no moodle', 'não é algo que eu faça por você'),
                             ('inicie o questionário', 'não é algo que eu faça por você')):
            reply = j.handle(text)
            self.assertEqual(reply.status, 'recusado', text)
            self.assertIn(reason, reply.text, text)
            self.assertIn('Não vou simular', reply.text)
        self.assertIn('prefiro não adivinhar', j.handle('qual a capital da França?').text)
        self.assertIn('Gmail institucional: não conectado', j.handle('o que está conectado?').text)

    def test_interrupting_and_failures_are_logged_honestly(self):
        self.with_reading()
        j = self.jarvis()
        reply = j.handle('prepare a tarefa em grupo', cancelled=lambda: True)
        self.assertEqual(reply.status, 'cancelado')
        self.assertEqual(reply.files, [])
        self.assertFalse(self.out.exists() and any(self.out.rglob('*.docx')))
        ops = self.store.operations()
        self.assertEqual((ops[0]['tool'], ops[0]['status']), ('preparar_atividade', 'cancelado'))
        with closing(sqlite3.connect(self.live)) as db:                           # Jarvis never writes live.db
            before = db.execute('SELECT COUNT(*) FROM companion_runs').fetchone()[0]
        j.handle('o que tenho para fazer hoje?')
        with closing(sqlite3.connect(self.live)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM companion_runs').fetchone()[0], before)
        self.assertIn('preparar_atividade • cancelado', j.handle('o que você fez?').text)


class PanelTests(Base):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def panel(self, clock=NOW):
        from campus_ai.jarvis_ui import JarvisPanel
        panel = JarvisPanel(store_path=self.dir / 'jarvis.db', live_db=self.live, output_dir=self.out, clock=lambda: clock,
                            reminder_interval_ms=3600000)
        self.addCleanup(self._destroy, panel)
        return panel

    @staticmethod
    def _destroy(panel):
        """Ends the panel's work and deletes it while the QApplication still exists (an orphan widget destroyed at
        interpreter exit crashed the process with an access violation after all tests had passed)."""
        from PySide6.QtCore import QCoreApplication, QEvent
        panel.shutdown()
        self_thread_left = panel.busy
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        assert not self_thread_left, 'a request thread was still running after shutdown'

    def test_a_typed_question_is_answered_in_the_transcript_with_the_files(self):
        self.with_reading()
        panel = self.panel()
        panel.input.setText('Jarvis, o que tenho para fazer hoje?')
        panel.send()
        self.assertTrue(panel.wait_idle())
        self.assertIn('Tarefa em grupo sintética', panel.transcript.toPlainText())
        panel.send('prepare essa atividade')
        self.assertTrue(panel.wait_idle())
        html = panel.transcript.toHtml()
        self.assertIn('.docx', html)
        self.assertEqual(panel.status.text(), 'Pronto.')
        reopened = self.panel()                                                    # history survives a restart
        self.assertIn('prepare essa atividade', reopened.transcript.toPlainText())

    def test_links_outside_the_delivery_folder_are_not_opened(self):
        from unittest import mock
        from PySide6.QtCore import QUrl
        panel = self.panel()
        with mock.patch('campus_ai.jarvis_ui.QDesktopServices.openUrl') as opened:
            panel._open_link(QUrl.fromLocalFile(str(self.dir / 'live.db')))
            opened.assert_not_called()
            self.out.mkdir(parents=True)
            inside = self.out / 'ok.md'
            inside.write_text('x', encoding='utf-8')
            panel._open_link(QUrl.fromLocalFile(str(inside)))
            opened.assert_called_once()

    def test_due_reminders_are_shown_once(self):
        store = JarvisStore(self.dir / 'jarvis.db')
        store.add_reminder(NOW - timedelta(minutes=1), 'Entrega da AV2')
        panel = self.panel()
        seen = []
        panel.reminder_due.connect(seen.append)
        panel.check_reminders()
        panel.check_reminders()
        self.assertEqual(seen, ['Lembrete: Entrega da AV2'])
        self.assertIn('Entrega da AV2', panel.transcript.toPlainText())


if __name__ == '__main__':
    unittest.main()
