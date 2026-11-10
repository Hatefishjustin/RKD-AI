$ErrorActionPreference = 'Stop'
$windowsIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$windowsPrincipal = New-Object System.Security.Principal.WindowsPrincipal($windowsIdentity)
if (-not $windowsPrincipal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator elevation is required. Open PowerShell with Run as administrator, approve UAC, then rerun this script. No tasks were changed.'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv/Scripts/pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Project Python runtime is required' }
$taskEvidence = Join-Path $projectRoot 'var/backups/nas/task-registration'
New-Item -ItemType Directory -Path $taskEvidence -Force | Out-Null
$identityName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identityName -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$definitions = @(
    @{ Name = 'RKD-AI-NAS-Offsite-Backup'; Script = 'sync_nas_backup.py'; Trigger = (New-ScheduledTaskTrigger -Daily -At '04:15') },
    @{ Name = 'RKD-AI-NAS-Offsite-Recovery'; Script = 'verify_offsite_restore.py'; Trigger = (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '04:45') }
)
foreach ($definition in $definitions) {
    $scriptPath = Join-Path $PSScriptRoot $definition.Script
    $existing = Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.Actions.Execute -ne $python -or $existing.Actions.Arguments -ne ('"' + $scriptPath + '"')) { throw 'An unrelated task uses the reserved RKD task name' }
        Export-ScheduledTask -TaskName $definition.Name | Set-Content -LiteralPath (Join-Path $taskEvidence ($definition.Name + '-before.xml')) -Encoding UTF8
    }
    $action = New-ScheduledTaskAction -Execute $python -Argument ('"' + $scriptPath + '"') -WorkingDirectory $projectRoot
    Register-ScheduledTask -TaskName $definition.Name -Action $action -Trigger $definition.Trigger -Principal $principal -Settings $settings -Description 'RKD private NAS offsite verification. Existing SSH key only; no live data replacement. Requires this Windows user session and Tailscale connectivity.' -Force | Out-Null
    Export-ScheduledTask -TaskName $definition.Name | Set-Content -LiteralPath (Join-Path $taskEvidence ($definition.Name + '.xml')) -Encoding UTF8
}
Get-ScheduledTask -TaskName 'RKD-AI-NAS-Offsite-*' | Select-Object TaskName, State
