$ErrorActionPreference = 'Stop'
$Target = Join-Path $env:LOCALAPPDATA 'MaiOsPulse'
if (Get-Process -Name 'MaiOsPulse' -ErrorAction SilentlyContinue) {
    throw 'Quit Pulse from its tray menu first. No process will be forcibly stopped.'
}
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'MaiOsPulse' -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path ([Environment]::GetFolderPath('Desktop')) 'mai-os Pulse.lnk') -ErrorAction SilentlyContinue
if (Test-Path $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
Write-Host 'Pulse removed. Preferences and exported snapshots are retained.'
