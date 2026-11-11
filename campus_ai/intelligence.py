"""Provider-neutral study boundary. No network, subprocess, audio or persistence.

Future Ollama/API/Codex adapters implement StudyProvider. The caller must show
the exact content and destination before creating a per-request Consent.
"""
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol


@dataclass(frozen=True)
class StudyRequest:
    question: str
    content: str

    def digest(self):
        return sha256((self.question + '\0' + self.content).encode()).hexdigest()


@dataclass(frozen=True)
class Consent:
    provider: str
    request_digest: str


class StudyProvider(Protocol):
    name: str
    def generate(self, request: StudyRequest) -> str: ...


class VoiceInput(Protocol):
    """Future explicit push-to-talk source; no implementation captures audio."""
    def capture_once(self) -> str: ...


class StudyAssistant:
    def __init__(self, provider: StudyProvider):
        self.provider = provider

    def generate(self, request: StudyRequest, consent: Consent | None) -> str:
        if consent is None or consent.provider != self.provider.name or consent.request_digest != request.digest():
            raise PermissionError('Autorize o conteúdo e o provedor para esta solicitação.')
        return 'Material de apoio — exige revisão do usuário.\n\n' + self.provider.generate(request)


def local_answer(question, items):
    """A small deterministic dashboard query, without claiming model inference."""
    if not items:
        return 'Nenhum item disponível nesta sessão. Execute uma análise autorizada primeiro.'
    query = question.casefold()
    if 'disciplina' in query:
        return 'Disciplinas identificadas:\n' + '\n'.join(sorted({i.course for i in items}))
    if any(word in query for word in ('prazo', 'pend', 'atividade', 'tarefa')):
        selected = sorted((i for i in items if i.category == 'assignment' and i.status != 'submitted'),
                          key=lambda i: i.due_iso or '9999')
        return '\n'.join(f'{i.course} — {i.title}: {i.due_iso or "prazo não informado"} ({i.status})'
                         for i in selected) or 'Nenhuma atividade não concluída identificada; confirme no AVA.'
    return ('Consulta local disponível: pergunte sobre disciplinas, atividades ou prazos. '
            'IA generativa ainda não conectada. APIs têm contratação própria; ChatGPT Plus não garante créditos de API.')
