<#
.SYNOPSIS
  Cria a .venv do Campus AI e instala as dependências, incluindo o modo navegador.

.DESCRIPTION
  Instala o pacote com o extra [browser] (Playwright), usado pela leitura com navegador dedicado e por
  parte da suíte de testes. Em seguida baixa o Chromium do Playwright para dentro da .venv
  (PLAYWRIGHT_BROWSERS_PATH=0, o mesmo local que o aplicativo usa ao abrir o navegador).
  Use -SemChromium para pular o download do Chromium (~150 MB): o modo Demonstração e a suíte padrão
  de testes funcionam sem ele; a leitura com navegador e os testes opt-in com Chromium, não.
#>
[CmdletBinding()]
param([switch]$SemChromium)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Instale o Python 3.11 ou mais recente com o Python Launcher (py).'
}
py -3 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Falha ao atualizar o pip.' }
& '.\.venv\Scripts\python.exe' -m pip install -e '.[browser]'
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar as dependências.' }
if (-not $SemChromium) {
    $env:PLAYWRIGHT_BROWSERS_PATH = '0'
    & '.\.venv\Scripts\python.exe' -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao baixar o Chromium do Playwright.' }
}
Write-Host "Instalação concluída. Inicie com .\scripts\abrir_windows.ps1" -ForegroundColor Green
