$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
& '.\.venv\Scripts\python.exe' -m pip install -e '.[build]'
& '.\.venv\Scripts\python.exe' -m PyInstaller --clean --noconfirm --windowed --onedir --name CampusAI --collect-all keyring --collect-all googleapiclient run_app.pyw
Write-Host 'Aplicativo gerado em dist\CampusAI\CampusAI.exe'
Write-Host 'Nota: scripts de inicialização neste MVP usam a instalação Python .venv, não o EXE.'
