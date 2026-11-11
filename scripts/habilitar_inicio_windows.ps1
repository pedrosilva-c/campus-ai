$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Instale o Campus AI antes de habilitar o início automático.' }
& $python -c 'from campus_ai.startup import configure; configure(True)'
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível configurar o início automático.' }
Write-Host 'Campus AI iniciará na bandeja ao entrar no Windows. Nenhuma análise foi autorizada por este comando.' -ForegroundColor Green
