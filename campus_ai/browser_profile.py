"""Windows ACL preflight for the dedicated, sensitive Chromium profile."""
from __future__ import annotations

import subprocess


class BrowserProfileUnsafe(RuntimeError):
    """The profile ACL was not confirmed private."""


# Static, read-only command: never prints ACL identities, paths, or browser data.
_VERIFY_ACL = r'''
try {
    $root = Join-Path $env:LOCALAPPDATA 'CampusAI'
    $profile = Join-Path $root 'browser_profile'
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $required = @($sid, 'S-1-5-18', 'S-1-5-32-544')
    foreach ($path in @($root, $profile)) {
        if (-not (Test-Path -LiteralPath $path -PathType Container)) { exit 1 }
        if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { exit 1 }
        $acl = Get-Acl -LiteralPath $path
        if (-not $acl.AreAccessRulesProtected) { exit 1 }
        if ($acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value -notin $required) { exit 1 }
        $seen = @{}
        foreach ($rule in $acl.Access) {
            if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow) { exit 1 }
            $principal = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
            if ($principal -notin $required) { exit 1 }
            if (($rule.FileSystemRights -band [Security.AccessControl.FileSystemRights]::FullControl) -eq
                [Security.AccessControl.FileSystemRights]::FullControl) { $seen[$principal] = $true }
        }
        foreach ($principal in $required) { if (-not $seen[$principal]) { exit 1 } }
    }
    exit 0
} catch { exit 1 }
'''


def verify_private_profile() -> None:
    """Fail closed. No ACL details or session data enter application messages."""
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', _VERIFY_ACL],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise BrowserProfileUnsafe('Não foi possível verificar a proteção da pasta Campus AI e do perfil.') from None
    if result.returncode != 0:
        raise BrowserProfileUnsafe('Pasta Campus AI ou perfil ausente ou com permissões amplas. Prepare-os antes de conectar.')
