"""OS-backed keyring for credentials. Never log/store tokens in plaintext."""
from __future__ import annotations

NAMESPACE = 'CampusAI:academico'


def _keyring():
    import keyring
    from keyring.backends.fail import Keyring as FailKeyring
    backend = keyring.get_keyring()
    if isinstance(backend, FailKeyring) or backend.priority <= 0:
        raise RuntimeError('Cofre de credenciais do sistema indisponível. Não serão salvos tokens sem criptografia.')
    return keyring


def set_secret(key: str, value: str) -> None:
    _keyring().set_password(NAMESPACE, key, value)


def get_secret(key: str) -> str | None:
    return _keyring().get_password(NAMESPACE, key)


def delete_secret(key: str) -> None:
    try:
        _keyring().delete_password(NAMESPACE, key)
    except Exception as exc:
        if exc.__class__.__name__ != 'PasswordDeleteError':
            raise
