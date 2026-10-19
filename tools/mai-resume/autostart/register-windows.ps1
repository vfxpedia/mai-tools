# Registers the scheduled task "mai-resume": starts at logon with no window (pythonw), and a 5-minute repeat that starts
# it again if it is not running (the task ignores a new start while one runs, and mai-resume itself allows one instance).
# Usage (normal user, no admin needed):  powershell -ExecutionPolicy Bypass -File register-windows.ps1 -Pythonw <path to pythonw.exe>
param([Parameter(Mandatory = $true)][string]$Pythonw, [string]$TaskName = 'mai-resume')
if (-not (Test-Path -LiteralPath $Pythonw)) { Write-Error "pythonw not found: $Pythonw"; exit 1 }
$action = New-ScheduledTaskAction -Execute $Pythonw -Argument '-m mai_resume run'
$me = [Security.Principal.WindowsIdentity]::GetCurrent().Name     # DOMAIN\user; a bare user name is refused (seen 10/20)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $me
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($logon, $repeat) -Settings $settings -Principal $principal `
    -Description 'mai-resume: warns AI coding sessions before a plan limit and wakes them after the reset' -Force | Out-Null
$t = Get-ScheduledTask -TaskName $TaskName
Write-Output ("registered {0}: state={1} triggers={2}" -f $t.TaskName, $t.State, $t.Triggers.Count)
