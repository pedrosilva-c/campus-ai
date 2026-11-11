<#
.SYNOPSIS
  Executa a suíte de testes do Campus AI isolada dos dados reais.

.DESCRIPTION
  Os testes redirecionam LOCALAPPDATA para uma pasta descartável antes de rodar (tests/_isolation.py) e
  falham se qualquer dado real (live.db, demo.db, config.json, pasta do host, chave HKCU do host) mudar.
  Este script só prepara TEMP/Qt e chama o unittest. Use -Navegador para incluir os testes opt-in com
  Chromium local (páginas fictícias; nenhum acesso à AEDB).
#>
[CmdletBinding()]
param([switch]$Navegador)
$ErrorActionPreference = 'Stop'
$project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $project
$tmp = Join-Path $project '.tmp-campus-ai'
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$env:TEMP = $tmp; $env:TMP = $tmp; $env:TMPDIR = $tmp
$env:QT_QPA_PLATFORM = 'offscreen'
if ($Navegador) { $env:CAMPUS_AI_BROWSER_SMOKE = '1' } else { Remove-Item Env:CAMPUS_AI_BROWSER_SMOKE -ErrorAction SilentlyContinue }
& (Join-Path $project '.venv\Scripts\python.exe') -m unittest discover -s tests
exit $LASTEXITCODE
