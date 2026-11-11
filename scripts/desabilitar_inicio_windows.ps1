$ErrorActionPreference = 'Stop'
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
if (Get-ItemProperty -LiteralPath $key -Name 'Campus AI' -ErrorAction SilentlyContinue) {
    Remove-ItemProperty -LiteralPath $key -Name 'Campus AI'
}
$shortcut = Join-Path ([Environment]::GetFolderPath('Startup')) 'Campus AI.lnk'
if (Test-Path -LiteralPath $shortcut) { Remove-Item -LiteralPath $shortcut }
Write-Host 'Inicialização automática desabilitada. O agente aberto pode ser encerrado pela bandeja.'
