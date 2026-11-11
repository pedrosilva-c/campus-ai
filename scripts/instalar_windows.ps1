$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Instale Python 3.11 ou 3.12 com o Python Launcher (py).'
}
py -3 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install --upgrade pip
& '.\.venv\Scripts\python.exe' -m pip install -e .
Write-Host "Instalação concluída. Inicie com .\scripts\abrir_windows.ps1" -ForegroundColor Green
