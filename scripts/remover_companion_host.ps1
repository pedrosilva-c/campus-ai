<#
.SYNOPSIS
  Remove o registro do host Native Messaging do Campus AI Companion do usuário Windows atual.

.DESCRIPTION
  NÃO FOI EXECUTADO. Sem -Aplicar, apenas mostra o que seria removido.
  Com -Aplicar: apaga somente a chave HKCU\Software\Google\Chrome\NativeMessagingHosts\br.campus_ai.companion
  e os dois arquivos que instalar_companion_host.ps1 cria em %LOCALAPPDATA%\CampusAI-Companion\ (a pasta é
  removida só se ficar vazia: os backups do live.db em ...\backup\ são PRESERVADOS). Não toca no banco
  live.db (as leituras já salvas continuam lá), no perfil do navegador, na extensão nem em outras chaves.
#>
[CmdletBinding()]
param([switch]$Aplicar)
$ErrorActionPreference = 'Stop'

$HostName = 'br.campus_ai.companion'
$Folder = Join-Path $env:LOCALAPPDATA 'CampusAI-Companion'
$Files = @((Join-Path $Folder 'campus_ai_companion_host.cmd'), (Join-Path $Folder "$HostName.json"))
$RegKey = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"

Write-Output 'Seria removido:'
Write-Output "  Registro: $RegKey (existe: $(Test-Path -LiteralPath $RegKey))"
foreach ($file in $Files) { Write-Output "  Arquivo:  $file (existe: $(Test-Path -LiteralPath $file))" }

if (-not $Aplicar) {
    Write-Output 'Simulação: nada foi alterado. Use -Aplicar para remover.'
    return
}

if (Test-Path -LiteralPath $RegKey) { Remove-Item -LiteralPath $RegKey -Force }
foreach ($file in $Files) { if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force } }
if ((Test-Path -LiteralPath $Folder) -and -not (Get-ChildItem -LiteralPath $Folder -Force)) {
    Remove-Item -LiteralPath $Folder -Force
}
Write-Output 'Host removido do usuário atual.'
