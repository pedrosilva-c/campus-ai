"""Jarvis + local model (Ollama API) — with a FAKE Ollama server on 127.0.0.1 (random port), never the real model.

Checks the privacy guards (loopback only, allowed models only, child-process environment), what is sent to the
model (only the sentence and the fixed intent list), the validation of its answer (closed list, no invented names,
no self-confirmation), and that everything keeps working when the model is off, slow, wrong or cancelled.
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from companion_snapshots import snapshot_dict  # noqa: E402
from test_companion_deadlines import CHECKED, VARIETY, with_details  # noqa: E402

from campus_ai import companion_store as cs  # noqa: E402
from campus_ai import contract  # noqa: E402
from campus_ai.jarvis import Jarvis, JarvisStore, llm  # noqa: E402

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


class FakeOllama:
    """Minimal Ollama API: /api/version, /api/tags, /api/chat (NDJSON stream). Records every request body."""

    def __init__(self):
        self.answer = {'intencao': 'desconhecido', 'alvo': 'nenhum'}
        self.delay = 0.0
        self.models = ['qwen3.5:4b']
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _json(self, body, status=200):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                fake.requests.append(('GET', self.path, None))
                if self.path == '/api/version':
                    self._json({'version': '0.0.0-teste'})
                elif self.path == '/api/tags':
                    self._json({'models': [{'name': m} for m in fake.models]})
                else:
                    self._json({'error': 'not found'}, 404)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fake.requests.append(('POST', self.path, body))
                if body.get('model') not in fake.models:
                    self._json({'error': 'model not found'}, 404)
                    return
                content = json.dumps(fake.answer, ensure_ascii=False)
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson')
                self.end_headers()
                for i in range(0, len(content), 8):              # streamed in small pieces, like the real server
                    time.sleep(fake.delay)
                    piece = {'message': {'role': 'assistant', 'content': content[i:i + 8]}, 'done': False}
                    try:
                        self.wfile.write((json.dumps(piece) + '\n').encode())
                        self.wfile.flush()
                    except OSError:
                        return
                self.wfile.write((json.dumps({'message': {'content': ''}, 'done': True}) + '\n').encode())

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def chats(self):
        return [body for method, path, body in self.requests if path == '/api/chat']


class GuardTests(unittest.TestCase):
    def test_only_loopback_addresses_and_allowed_models(self):
        for good in ('http://127.0.0.1:11434', 'http://localhost:11434', 'http://[::1]:11434'):
            self.assertTrue(llm.check_url(good).startswith('http://'))
        for bad in ('http://0.0.0.0:11434', 'http://192.168.0.10:11434', 'https://127.0.0.1:11434', 'http://ollama.com',
                    'http://127.0.0.1:11434/v1', 'http://user:x@127.0.0.1:11434', 'http://127.0.0.1.evil.com:11434'):
            with self.assertRaises(llm.LocalModelError, msg=bad):
                llm.check_url(bad)
        self.assertEqual(llm.check_model('qwen3.5:4b'), 'qwen3.5:4b')
        for bad in ('qwen3.5:4b-cloud', 'gemma4:cloud', 'gemma4:31b-cloud', 'qwen3.5:9b', 'llama3', ''):
            with self.assertRaises(llm.LocalModelError, msg=bad):
                llm.check_model(bad)

    def test_the_server_environment_is_local_only_and_never_touches_the_global_one(self):
        base = {'PATH': 'x', 'OLLAMA_ORIGINS': '*', 'HTTPS_PROXY': 'http://proxy', 'OLLAMA_HOST': '0.0.0.0'}
        env = llm.server_environment(base)
        self.assertEqual((env['OLLAMA_HOST'], env['OLLAMA_NO_CLOUD']), ('127.0.0.1:11434', '1'))
        self.assertNotIn('OLLAMA_ORIGINS', env)
        self.assertNotIn('HTTPS_PROXY', env)
        self.assertEqual(base['OLLAMA_HOST'], '0.0.0.0')                      # the given mapping is not changed
        self.assertNotEqual(os.environ.get('OLLAMA_NO_CLOUD'), '1') if 'OLLAMA_NO_CLOUD' not in os.environ else None

    def test_the_answer_is_validated_against_the_closed_list(self):
        sentence = 'monta um material pro trabalho de casos de uso'
        self.assertIsNone(llm.validate({'intencao': 'executar_comando'}, sentence))
        self.assertIsNone(llm.validate({'intencao': 'confirmar'}, sentence))             # never self-confirms
        self.assertIsNone(llm.validate({'intencao': 'desconhecido'}, sentence))
        ok = llm.validate({'intencao': 'preparar_atividade', 'alvo': 'referencia', 'referencia': 'casos de uso'}, sentence)
        self.assertEqual((ok.name, ok.slots), ('preparar_atividade', {'alvo': 'referencia', 'referencia': 'casos de uso'}))
        invented = llm.validate({'intencao': 'preparar_atividade', 'alvo': 'referencia',
                                 'referencia': 'Diagrama de Classes do PDV'}, sentence)
        self.assertEqual(invented.slots, {'alvo': 'nenhum'})                               # a name not said is dropped
        self.assertEqual(llm.validate({'intencao': 'preparar_atividade', 'alvo': 'apagar'}, sentence).slots['alvo'], 'nenhum')
        memory = 'anota que a prova vale 4 pontos'
        self.assertEqual(llm.validate({'intencao': 'memoria_adicionar', 'texto': 'a prova vale 4 pontos'}, memory).slots,
                         {'texto': 'a prova vale 4 pontos'})
        self.assertIsNone(llm.validate({'intencao': 'memoria_adicionar', 'texto': 'o exame final é eliminatório'}, memory))


class RouterAndAgentTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeOllama()
        self.addCleanup(self.fake.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.live = self.dir / 'live.db'
        cs.SnapshotStore(self.live, allowed_courses=['7653']).save(
            contract.parse_snapshot(with_details(snapshot_dict(generated=CHECKED), VARIETY)), received_at=CHECKED)

    def jarvis(self, client=None, **kw):
        client = client or llm.OllamaClient(self.fake.url, **kw)
        self.store = JarvisStore(self.dir / 'jarvis.db')
        return Jarvis(self.store, live_db=self.live, output_dir=self.dir / 'out', clock=lambda: NOW,
                      router=llm.IntentRouter(client))

    def test_status_reports_server_and_model(self):
        status = llm.OllamaClient(self.fake.url).status()
        self.assertTrue(status.ready)
        self.assertIn('conectada — qwen3.5:4b', status.text())
        self.fake.models = ['outro:1b']
        self.assertIn('não está instalado', llm.OllamaClient(self.fake.url).status().text())
        self.fake.close()
        off = llm.OllamaClient(self.fake.url).status()
        self.assertFalse(off.server)
        self.assertIn('desligada', off.text())

    def test_rules_first_the_model_only_for_what_they_do_not_understand(self):
        j = self.jarvis()
        reply = j.handle('Jarvis, o que tenho para fazer hoje?')
        self.assertEqual((reply.source, self.fake.chats()), ('regras', []))
        self.fake.answer = {'intencao': 'pendencias', 'alvo': 'nenhum'}
        reply = j.handle('tem alguma coisa pendurada pra mim na faculdade?')         # the rules do not know this one
        self.assertEqual(reply.intent, 'pendencias')
        self.assertEqual(reply.source, 'ia_local:qwen3.5:4b')
        self.assertIn('Tarefa em grupo sintética', reply.text)                         # the answer comes from the tool
        ops = self.store.operations(1)[0]
        self.assertEqual(ops['arguments']['interpretado_por'], 'ia_local:qwen3.5:4b')

    def test_only_the_sentence_and_the_intent_list_reach_the_model(self):
        j = self.jarvis()
        j.handle('lembre que meu grupo é com a Ana e o Bruno')                         # a memory, by the rules
        self.fake.answer = {'intencao': 'proximos_prazos', 'alvo': 'nenhum'}
        j.handle('qual dessas coisas aí eu devia olhar primeiro, hein?')
        (body,) = self.fake.chats()
        sent = json.dumps(body, ensure_ascii=False)
        for private in ('Tarefa em grupo sintética', 'Exercício sintético', 'Ana e o Bruno', 'moodle:course', '7653',
                        'Disciplina fictícia'):
            self.assertNotIn(private, sent, private)
        self.assertEqual(body['model'], 'qwen3.5:4b')
        self.assertFalse(body['think'])
        self.assertEqual(body['messages'][-1], {'role': 'user', 'content': 'qual dessas coisas aí eu devia olhar primeiro, hein?'})
        self.assertEqual(body['format']['properties']['intencao']['enum'], list(llm.INTENTS))

    def test_final_refusals_and_secrets_are_never_sent_to_the_model(self):
        j = self.jarvis()
        self.fake.answer = {'intencao': 'pendencias', 'alvo': 'nenhum'}
        for text in ('envie um e-mail para o professor', 'submeta a tarefa no moodle', 'inicie o questionário',
                     'minha senha do moodle é abc123, guarda?'):
            reply = j.handle(text)
            self.assertNotEqual(reply.intent, 'pendencias', text)
        self.assertEqual(self.fake.chats(), [])
        weak = j.handle('tem algo que eu esqueci de mandar?')                         # weak word: the model re-reads it
        self.assertEqual((weak.intent, weak.source), ('pendencias', 'ia_local:qwen3.5:4b'))

    def test_a_wrong_or_unknown_answer_runs_nothing(self):
        j = self.jarvis()
        for answer in ({'intencao': 'confirmar', 'alvo': 'nenhum'}, {'intencao': 'apagar_tudo'}, {'nada': 1}):
            self.fake.answer = answer
            reply = j.handle('faz aquilo que eu te pedi ontem')
            self.assertEqual(reply.intent, 'desconhecido', answer)
            self.assertEqual(reply.files, [])
            self.assertIn('prefiro não adivinhar', reply.text)
        self.store.set_context('pending', {'action': 'apagar_memoria', 'id': 1})
        self.fake.answer = {'intencao': 'confirmar', 'alvo': 'nenhum'}
        j.handle('manda ver nisso aí então')                                           # unknown to the rules
        self.assertIsNone(self.store.context('pending'))                              # dropped, never confirmed
        self.assertIsNotNone(self.fake.chats())

    def test_off_slow_or_cancelled_model_the_rules_keep_working(self):
        j = self.jarvis()
        self.fake.close()
        reply = j.handle('faz aquilo que eu te pedi ontem')
        self.assertEqual(reply.intent, 'desconhecido')
        self.assertIn('IA local desligada', reply.text)
        self.assertIn('Tarefa em grupo sintética', j.handle('o que tenho para fazer?').text)   # rules still answer
        slow = FakeOllama()
        self.addCleanup(slow.close)
        slow.answer = {'intencao': 'pendencias', 'alvo': 'nenhum'}
        slow.delay = 0.3
        timed = self.jarvis(llm.OllamaClient(slow.url, read_timeout=0.2))
        self.assertIn('IA local', timed.handle('faz aquilo que eu te pedi ontem').text)
        stop = threading.Event()
        threading.Timer(0.5, stop.set).start()
        cancelled = self.jarvis(llm.OllamaClient(slow.url)).handle('faz aquilo que eu te pedi ontem', cancelled=stop.is_set)
        self.assertEqual(cancelled.status, 'cancelado')

    def test_the_most_urgent_activity_is_chosen_deterministically(self):
        j = self.jarvis()
        reply = j.handle('Jarvis, veja minhas próximas atividades, identifique a que vence primeiro e prepare um documento para mim.')
        self.assertEqual(self.fake.chats(), [])                                         # understood by the rules
        self.assertIn('A mais urgente é "Tarefa em grupo sintética": está atrasada.', reply.text)
        self.assertIn('Próximas atividades com prazo verificado', reply.text)
        self.assertEqual(len(reply.files), 2)
        md = Path(reply.files[1]).read_text(encoding='utf-8')
        for section in ('1. Informações fornecidas pelo professor', 'NÃO DISPONÍVEIS', '2. Dados verificados',
                        '3. Análise do Campus AI', '4. Instruções e plano', '5. Checklist', '6. Conteúdo preparado',
                        '7. Informações ausentes'):
            self.assertIn(section, md, section)
        self.fake.answer = {'intencao': 'preparar_atividade', 'alvo': 'mais_urgente'}
        via_model = j.handle('bora fazer um negócio pro trampo que tá pegando fogo')
        self.assertEqual(via_model.source, 'ia_local:qwen3.5:4b')
        self.assertIn('A mais urgente é "Tarefa em grupo sintética"', via_model.text)

    def test_without_verified_deadlines_it_does_not_pick_one(self):
        other = self.dir / 'sem_prazos.db'
        cs.SnapshotStore(other, allowed_courses=['7653']).save(contract.parse_snapshot(snapshot_dict(generated=CHECKED)),
                                                               received_at=CHECKED)
        store = JarvisStore(self.dir / 'j2.db')
        j = Jarvis(store, live_db=other, output_dir=self.dir / 'out2', clock=lambda: NOW)
        reply = j.handle('Identifique a atividade mais urgente e prepare um documento para mim.')
        self.assertEqual(reply.files, [])
        self.assertIn('Não consigo identificar a atividade mais urgente: nenhum prazo foi verificado ainda', reply.text)
        self.assertIn('Não vou escolher no chute', reply.text)


if __name__ == '__main__':
    unittest.main()
