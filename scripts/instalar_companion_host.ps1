<#
.SYNOPSIS
  Registra o host Native Messaging do Campus AI Companion SOMENTE para o usuário Windows atual.

.DESCRIPTION
  Revise antes de usar. Sem -Aplicar, apenas mostra o plano, o manifesto e o lançador e não altera nada.
  Com -Aplicar (somente com autorização explícita do aluno), nesta ordem:
    1. faz BACKUP do live.db (cópia consistente pela API de backup do SQLite, com integrity_check) em
       %LOCALAPPDATA%\CampusAI-Companion\backup\ — se falhar, para antes de qualquer outra alteração;
    2. grava em %LOCALAPPDATA%\CampusAI-Companion\ (FORA de %LOCALAPPDATA%\CampusAI, cujas entradas o
       script preparar_perfil_moodle_windows.ps1 controla) o lançador .cmd (Python da .venv do projeto,
       -E -s, módulo campus_ai.companion_host) e o manifesto do host, com allowed_origins = somente a
       extensão Campus AI Companion;
    3. cria UMA chave: HKCU\Software\Google\Chrome\NativeMessagingHosts\br.campus_ai.companion.
  Não usa HKLM, não pede administrador, não altera ACLs, não baixa nada, não inicia o host.
  Reverter: scripts\remover_companion_host.ps1 -Aplicar
#>
[CmdletBinding()]
param([switch]$Aplicar)
$ErrorActionPreference = 'Stop'

$HostName = 'br.campus_ai.companion'
$ExtensionId = 'oglmhecabakelhiaiandpdonpblldhnn'
$Project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Python = Join-Path $Project '.venv\Scripts\python.exe'
$Folder = Join-Path $env:LOCALAPPDATA 'CampusAI-Companion'
$BackupDir = Join-Path $Folder 'backup'
$LiveDb = Join-Path $env:LOCALAPPDATA 'CampusAI\live.db'
$Launcher = Join-Path $Folder 'campus_ai_companion_host.cmd'
$ManifestPath = Join-Path $Folder "$HostName.json"
$RegKey = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Python da .venv não encontrado: $Python" }
if (($Project + $Folder) -match '[^\x20-\x7E]') { throw 'Caminhos com caracteres não ASCII não são suportados pelo lançador .cmd.' }

$LauncherText = "@echo off`r`ncd /d `"$Project`"`r`n`"$Python`" -E -s -m campus_ai.companion_host %*`r`n"
$Manifest = [ordered]@{
    name            = $HostName
    description     = 'Campus AI Companion - host local (somente leitura recebida da extensao)'
    path            = $Launcher
    type            = 'stdio'
    allowed_origins = @("chrome-extension://$ExtensionId/")
}
$ManifestText = $Manifest | ConvertTo-Json -Depth 3

Write-Output 'Plano (usuário atual apenas):'
Write-Output "  Backup:     $LiveDb -> $BackupDir (existe live.db: $(Test-Path -LiteralPath $LiveDb))"
Write-Output "  Pasta:      $Folder"
Write-Output "  Lançador:   $Launcher"
Write-Output "  Manifesto:  $ManifestPath"
Write-Output "  Registro:   $RegKey (valor padrão = caminho do manifesto)"
Write-Output "  Extensão:   chrome-extension://$ExtensionId/"
Write-Output '--- manifesto do host ---'
Write-Output $ManifestText
Write-Output '--- lançador ---'
Write-Output $LauncherText

if (-not $Aplicar) {
    Write-Output 'Simulação: nada foi alterado. Use -Aplicar somente com autorização explícita.'
    return
}

if (Test-Path -LiteralPath $LiveDb) {
    Push-Location -LiteralPath $Project
    try {
        & $Python -E -s -m campus_ai.companion_store backup $BackupDir
        if ($LASTEXITCODE -ne 0) { throw 'Backup do live.db falhou; nada foi registrado.' }
    } finally {
        Pop-Location
    }
}
New-Item -ItemType Directory -Path $Folder -Force | Out-Null
[System.IO.File]::WriteAllText($Launcher, $LauncherText, [System.Text.Encoding]::ASCII)
[System.IO.File]::WriteAllText($ManifestPath, $ManifestText, (New-Object System.Text.UTF8Encoding $false))
New-Item -Path $RegKey -Force | Out-Null
Set-ItemProperty -Path $RegKey -Name '(default)' -Value $ManifestPath
Write-Output 'Host registrado para o usuário atual. Recarregue a extensão de integração no Chrome.'
