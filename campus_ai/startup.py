"""Opt-in Windows login startup via the current user's Run key (no shell)."""
from pathlib import Path
import subprocess
import sys
import os

KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
NAME = 'Campus AI'


def legacy_shortcut() -> Path:
    return Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup/Campus AI.lnk'


def command() -> str:
    if getattr(sys, 'frozen', False):
        args = [sys.executable, '--startup']
    else:
        executable = Path(sys.executable).with_name('pythonw.exe')
        script = Path(__file__).resolve().parent.parent / 'run_app.pyw'
        if not executable.is_file() or not script.is_file():
            raise OSError('Instalação Windows não encontrada.')
        args = [str(executable), str(script), '--startup']
    return subprocess.list2cmdline(args)


def enabled() -> bool:
    if sys.platform != 'win32':
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            value, _ = winreg.QueryValueEx(key, NAME)
            return value == command()
    except FileNotFoundError:
        return legacy_shortcut().is_file()


def configure(enable: bool):
    if sys.platform != 'win32':
        raise OSError('Inicialização disponível somente no Windows.')
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enable:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass
    # Migrate the exact shortcut created by earlier Campus AI releases.
    legacy_shortcut().unlink(missing_ok=True)
