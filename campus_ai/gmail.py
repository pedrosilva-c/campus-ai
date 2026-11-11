"""Gmail metadata read-only via desktop OAuth; refresh tokens in OS keyring."""
from __future__ import annotations
import json
from pathlib import Path
from .models import AcademicItem
from .security import get_secret, set_secret, delete_secret

GMAIL_SCOPE = ['https://www.googleapis.com/auth/gmail.readonly']
CREDENTIAL_KEY = 'gmail-oauth-json'
IMPORTANT_TERMS = ('prazo', 'prova', 'aviso importante', 'comunicado',
                   'calendário', 'calendario', 'matrícula', 'matricula',
                   'cancelamento', 'inscrição', 'inscricao')


def is_important(subject: str, labels=()) -> bool:
    """Conservative local classification of headers; message text is untrusted data."""
    return 'IMPORTANT' in labels or any(term in subject.casefold() for term in IMPORTANT_TERMS)


def connect_gmail(credentials_file: str):
    from google_auth_oauthlib.flow import InstalledAppFlow
    filepath = Path(credentials_file)
    if not filepath.is_file():
        raise FileNotFoundError('Não encontrei credentials.json do Google Cloud.')
    doc = json.loads(filepath.read_text(encoding='utf8'))
    if 'installed' not in doc:
        raise ValueError('Crie credenciais Google do tipo Aplicativo para computador (Desktop).')
    flow = InstalledAppFlow.from_client_secrets_file(str(filepath), GMAIL_SCOPE)
    cred = flow.run_local_server(host='localhost', port=0, open_browser=True,
                                 authorization_prompt_message='Conclua a autorização no navegador.',
                                 success_message='Campus AI autorizado. Volte ao aplicativo.',
                                 timeout_seconds=180)
    set_secret(CREDENTIAL_KEY, cred.to_json())


def disconnect_gmail():
    delete_secret(CREDENTIAL_KEY)


def gmail_enabled() -> bool:
    return bool(get_secret(CREDENTIAL_KEY))


def _credentials():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    saved = get_secret(CREDENTIAL_KEY)
    if not saved:
        raise RuntimeError('Gmail não está conectado; use Configurações > Conectar Gmail.')
    cred = Credentials.from_authorized_user_info(json.loads(saved), GMAIL_SCOPE)
    if not cred.valid:
        if cred.expired and cred.refresh_token:
            cred.refresh(Request())
            set_secret(CREDENTIAL_KEY, cred.to_json())
        else:
            raise RuntimeError('A sessão do Google expirou; conecte o Gmail novamente.')
    return cred


def scan_gmail(query: str, max_emails: int = 30, service=None) -> list[AcademicItem]:
    if service is None:
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=_credentials(), cache_discovery=False)
    results = service.users().messages().list(userId='me', q=query, maxResults=max_emails).execute()
    items = []
    for entry in results.get('messages', []):
        data = service.users().messages().get(userId='me', id=entry['id'],
                  format='metadata', metadataHeaders=['Subject', 'From', 'Date']).execute()
        headers = {h['name'].lower(): h['value'] for h in (data.get('payload') or {}).get('headers', [])}
        sender = headers.get('from', 'Remetente não informado')
        subject = headers.get('subject', '(Sem assunto)')
        snippet = data.get('snippet', '')
        tid = data.get('threadId', entry['id'])
        items.append(AcademicItem(uid=f'gmail:{entry["id"]}', source='gmail', category='message',
                title=subject, course='E-mail Institucional', description=f'De: {sender}\nData: {headers.get("date", "")}\n\n{snippet}',
                url=f'https://mail.google.com/mail/u/0/#all/{tid}',
                meta={'message_id': entry['id'], 'sender': sender,
                      'important': is_important(subject, data.get('labelIds') or ())}))
    return items
