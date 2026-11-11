$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$pythonw = Join-Path (Get-Location) '.venv\Scripts\pythonw.exe'
$script = Join-Path (Get-Location) 'run_app.pyw'
if (!(Test-Path $pythonw)) { throw 'Execute scripts\instalar_windows.ps1 primeiro.' }
Start-Process -FilePath $pythonw -ArgumentList ('"' + $script + '"') -WorkingDirectory (Get-Location).Path
