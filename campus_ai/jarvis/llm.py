"""Local language model (Ollama on this computer) as a FALLBACK interpreter of what the student asked.

Role, and only this role: when the deterministic rules (nlu.py) do not understand a sentence, the local model
picks ONE intent from a closed list and a few bounded arguments. The agent then validates and runs its existing
tools; the answer is always built by the tools from the real data. The model never answers with facts, never runs
anything, never sees the database, never confirms an action.

What is sent to the model: the student's sentence and the fixed list of intents. NOT sent: activity titles, Moodle
data, memories, documents, conversation history. A sentence that looks like a secret is not sent at all.

Privacy guards: only a loopback address (127.0.0.1 / localhost / ::1) is accepted; proxies from the environment
are ignored (trust_env=False); only models in ALLOWED_MODELS, never a name containing "cloud". The server this
module can start runs with OLLAMA_HOST=127.0.0.1:11434 and OLLAMA_NO_CLOUD=1 set for THAT child process only
(no global or registry change).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .store import fold, looks_secret

DEFAULT_URL = 'http://127.0.0.1:11434'
DEFAULT_MODEL = 'qwen3.5:4b'
ALLOWED_MODELS = ('qwen3.5:4b',)
LOOPBACK = ('127.0.0.1', 'localhost', '::1')
MAX_SENTENCE = 600


class LocalModelError(Exception):
    """The local model could not be used. ``code`` is a fixed identifier."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Cancelled(Exception):
    pass


def check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != 'http' or parts.hostname not in LOOPBACK or parts.username or parts.password \
            or parts.path not in ('', '/') or parts.query or parts.fragment:
        raise LocalModelError('endereco_nao_local')
    return f'http://{parts.netloc}'


def check_model(name: str) -> str:
    if not isinstance(name, str) or 'cloud' in name.lower() or name not in ALLOWED_MODELS:
        raise LocalModelError('modelo_nao_permitido')
    return name


@dataclass
class Status:
    server: bool = False
    model_present: bool = False
    version: str = ''
    model: str = DEFAULT_MODEL
    error: str = ''

    @property
    def ready(self) -> bool:
        return self.server and self.model_present

    def text(self) -> str:
        if self.ready:
            return f'IA local: conectada — {self.model} (Ollama {self.version}, somente neste computador)'
        if self.server:
            return f'IA local: Ollama {self.version} ativo, mas o modelo {self.model} não está instalado — usando só as regras'
        return 'IA local: desligada — usando a interpretação por regras (tudo continua funcionando)'


class OllamaClient:
    def __init__(self, url: str = DEFAULT_URL, model: str = DEFAULT_MODEL, *, session=None,
                 connect_timeout: float = 1.5, read_timeout: float = 90.0):
        import requests
        self.url = check_url(url)
        self.model = check_model(model)
        self.session = session or requests.Session()
        self.session.trust_env = False                    # never through a proxy from the environment
        self.timeouts = (connect_timeout, read_timeout)

    def status(self) -> Status:
        status = Status(model=self.model)
        try:
            version = self.session.get(f'{self.url}/api/version', timeout=(self.timeouts[0], 3))
            version.raise_for_status()
            status.server, status.version = True, str(version.json().get('version', ''))[:20]
            tags = self.session.get(f'{self.url}/api/tags', timeout=(self.timeouts[0], 5))
            tags.raise_for_status()
            names = {m.get('name') or m.get('model') for m in tags.json().get('models', [])}
            status.model_present = self.model in names
        except Exception as exc:                           # offline is a normal state, not a crash
            status.error = exc.__class__.__name__
        return status

    def warm_up(self) -> bool:
        """Loads the model into memory (an empty generate), so the first question does not wait for the load."""
        try:
            response = self.session.post(f'{self.url}/api/generate', json={'model': self.model, 'prompt': '',
                                                                            'keep_alive': '10m'}, timeout=(self.timeouts[0], 180))
            return response.status_code == 200
        except Exception:
            return False

    def chat_json(self, messages, schema: dict, *, cancelled=lambda: False, deadline_s: float = 90.0) -> dict:
        """One structured answer (JSON matching ``schema``), streamed so that a cancel stops it mid-way."""
        body = {'model': self.model, 'messages': messages, 'stream': True, 'format': schema, 'think': False,
                'options': {'temperature': 0, 'num_ctx': 4096, 'num_predict': 256}, 'keep_alive': '10m'}
        started = time.monotonic()
        parts = []
        try:
            response = self.session.post(f'{self.url}/api/chat', json=body, stream=True, timeout=self.timeouts)
        except Exception:
            raise LocalModelError('ia_local_indisponivel') from None
        with response:
            if response.status_code == 404:
                raise LocalModelError('modelo_ausente')
            if response.status_code != 200:
                raise LocalModelError('ia_local_erro')
            try:
                for line in response.iter_lines():
                    if cancelled():
                        raise Cancelled()
                    if time.monotonic() - started > deadline_s:
                        raise LocalModelError('tempo_esgotado')
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get('error'):
                        raise LocalModelError('ia_local_erro')
                    parts.append((chunk.get('message') or {}).get('content') or '')
                    if chunk.get('done'):
                        break
            except (Cancelled, LocalModelError):
                raise
            except Exception:
                raise LocalModelError('ia_local_erro') from None
        try:
            answer = json.loads(''.join(parts))
        except ValueError:
            raise LocalModelError('resposta_invalida') from None
        if not isinstance(answer, dict):
            raise LocalModelError('resposta_invalida')
        return answer


# --- the closed list the model may choose from ------------------------------------------------------------------------
# name: description shown to the model. Never in this list: confirmar, cancelar_pendente, escolher (the student's own
# "sim"/"não"/number are always handled by the deterministic rules).
INTENTS = {
    'hoje': 'o que o estudante tem para fazer HOJE ou no dia',
    'pendencias': 'tudo o que ainda falta fazer ou entregar (sem falar de um dia específico)',
    'proximos_prazos': 'quais atividades vencem primeiro / próximos prazos / ordenar por prazo',
    'atrasadas': 'se há atividades atrasadas ou vencidas',
    'nao_entregues': 'atividades ainda não entregues ou não enviadas',
    'entregues': 'atividades já entregues, enviadas, avaliadas ou aguardando nota',
    'panorama': 'explicar a situação geral: o que está pendente e o que já foi concluído',
    'planejar_semana': 'organizar a semana, plano de estudos, cronograma',
    'preparar_atividade': 'preparar, montar material, documento ou roteiro para uma atividade',
    'lembrete_criar': 'pedir para ser avisado ou lembrado em um momento',
    'lembrete_listar': 'ver os lembretes',
    'memoria_adicionar': 'pedir para guardar/anotar uma informação pessoal na memória',
    'memoria_listar': 'perguntar o que o assistente sabe ou lembra',
    'buscar_conversa': 'procurar algo que foi dito em conversas anteriores',
    'integracoes': 'perguntar o que está conectado (Moodle, Gmail, agenda, IA)',
    'historico': 'perguntar o que o assistente já executou',
    'ajuda': 'perguntar o que o assistente sabe fazer',
    'nao_suportado': 'pedido de ação externa (enviar e-mail, entregar atividade, responder questionário, pesquisar na '
                     'internet, resumir matéria)',
    'desconhecido': 'nada acima / conversa fora do escopo',
}
TARGETS = ('nenhum', 'mais_urgente', 'contexto', 'referencia')
SCHEMA = {
    'type': 'object',
    'properties': {
        'intencao': {'type': 'string', 'enum': list(INTENTS)},
        'alvo': {'type': 'string', 'enum': list(TARGETS)},
        'referencia': {'type': 'string', 'maxLength': 120},
        'texto': {'type': 'string', 'maxLength': 400},
    },
    'required': ['intencao', 'alvo'],
}
SYSTEM = (
    'Você é o classificador de pedidos do Campus AI, um assistente acadêmico local. Você NÃO responde ao pedido: '
    'apenas devolve JSON com a intenção. Regras:\n'
    '- "intencao": exatamente uma das opções abaixo.\n'
    '- "alvo" (só para preparar_atividade): "mais_urgente" quando o pedido fala da atividade que vence primeiro, mais '
    'urgente ou mais próxima; "contexto" quando diz "essa", "esta", "ela", "aquela"; "referencia" quando nomeia a '
    'atividade; senão "nenhum".\n'
    '- "referencia": copie EXATAMENTE as palavras que o estudante usou para nomear a atividade ou o assunto. Nunca '
    'invente nomes.\n'
    '- "texto" (só para memoria_adicionar): a informação a guardar, com as palavras do estudante.\n'
    '- Na dúvida, use "desconhecido".\n\nIntenções:\n'
    + '\n'.join(f'- {name}: {desc}' for name, desc in INTENTS.items())
)
EXAMPLES = [
    ('tô devendo alguma coisa na faculdade?', {'intencao': 'pendencias', 'alvo': 'nenhum'}),
    ('qual trabalho tenho que entregar antes?', {'intencao': 'proximos_prazos', 'alvo': 'nenhum'}),
    ('monta um material pro trabalho que vence primeiro', {'intencao': 'preparar_atividade', 'alvo': 'mais_urgente'}),
    ('anota aí que o professor aceita entrega em PDF', {'intencao': 'memoria_adicionar', 'alvo': 'nenhum',
                                                        'texto': 'o professor aceita entrega em PDF'}),
    ('qual a capital da França?', {'intencao': 'desconhecido', 'alvo': 'nenhum'}),
]


@dataclass
class Routed:
    name: str
    slots: dict = field(default_factory=dict)


def _words(text: str):
    return [w for w in fold(text).replace(',', ' ').replace('.', ' ').split() if len(w) > 2]


def _from_user(value: str, sentence: str) -> str:
    """The argument only if every meaningful word of it is in the student's sentence (no invented names)."""
    value = ' '.join(str(value or '').split())[:120]
    words = _words(value)
    folded = fold(sentence)
    return value if words and all(w in folded for w in words) else ''


class IntentRouter:
    def __init__(self, client: OllamaClient):
        self.client = client

    @property
    def model(self) -> str:
        return self.client.model

    def route(self, sentence: str, cancelled=lambda: False) -> Routed | None:
        sentence = ' '.join(str(sentence or '').split())[:MAX_SENTENCE]
        if not sentence or looks_secret(sentence):
            return None                                       # never send something that looks like a secret
        messages = [{'role': 'system', 'content': SYSTEM}]
        for question, answer in EXAMPLES:
            messages += [{'role': 'user', 'content': question}, {'role': 'assistant', 'content': json.dumps(answer, ensure_ascii=False)}]
        messages.append({'role': 'user', 'content': sentence})
        answer = self.client.chat_json(messages, SCHEMA, cancelled=cancelled)
        return validate(answer, sentence)


def validate(answer: dict, sentence: str) -> Routed | None:
    """Turns the model's JSON into an allowed intent with checked arguments, or None."""
    name = answer.get('intencao')
    if name not in INTENTS or name == 'desconhecido':
        return None
    slots = {}
    if name == 'preparar_atividade':
        target = answer.get('alvo') if answer.get('alvo') in TARGETS else 'nenhum'
        reference = _from_user(answer.get('referencia', ''), sentence)
        if target == 'referencia' and not reference:
            target = 'nenhum'
        slots['alvo'] = target
        if reference:
            slots['referencia'] = reference
    elif name == 'memoria_adicionar':
        text = ' '.join(str(answer.get('texto') or '').split())[:400]
        words = _words(text)
        folded = fold(sentence)
        if not words or sum(w in folded for w in words) < max(1, int(0.8 * len(words))) or looks_secret(text):
            return None                                       # paraphrased or sensitive: let the rules ask again
        slots['texto'] = text
    elif name in ('buscar_conversa', 'memoria_listar'):
        reference = _from_user(answer.get('referencia', ''), sentence)
        if reference:
            slots['sobre'] = reference
    return Routed(name, slots)


# --- the local server this app can start (portable Ollama, no installer, no registry) --------------------------------
def ollama_home() -> Path:
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CampusAI-Ollama'


def find_executable(home: Path | None = None) -> Path | None:
    home = home or ollama_home()
    candidates = sorted(home.glob('v*/ollama.exe'), key=lambda p: [int(x) if x.isdigit() else 0
                                                                   for x in p.parent.name.lstrip('v').split('.')])
    return candidates[-1] if candidates else None


def server_environment(base: dict | None = None) -> dict:
    """Environment for the child process only: loopback, cloud off, one model at a time."""
    env = dict(base if base is not None else os.environ)
    for key in ('OLLAMA_ORIGINS', 'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY'):
        env.pop(key, None)
    env.update({'OLLAMA_HOST': '127.0.0.1:11434', 'OLLAMA_NO_CLOUD': '1', 'OLLAMA_KEEP_ALIVE': '10m',
                'OLLAMA_MAX_LOADED_MODELS': '1', 'OLLAMA_NUM_PARALLEL': '1', 'OLLAMA_NOHISTORY': '1'})
    return env


class LocalServer:
    """Starts ``ollama serve`` (hidden window) if it is not running and stops it on exit if this app started it."""

    def __init__(self, executable: Path | None = None, log_dir: Path | None = None):
        self.executable = executable if executable is not None else find_executable()
        self.log_dir = log_dir or ollama_home() / 'logs'
        self.process = None

    def start(self) -> bool:
        if self.executable is None or not Path(self.executable).is_file() or self.process is not None:
            return False
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log = open(self.log_dir / 'server.log', 'ab')
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
        self.process = subprocess.Popen([str(self.executable), 'serve'], env=server_environment(), stdout=log,
                                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, creationflags=flags)
        log.close()
        return True

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
