param(
  [string]$TaskName = "HohaiDailyCheckin",
  [string]$ProjectDir = "$PSScriptRoot",
  [string]$RunTime = "08:08"
)

$batPath = Join-Path $ProjectDir "checkin_windows.bat"
if (!(Test-Path $batPath)) {
  Write-Error "checkin_windows.bat not found: $batPath"
  exit 1
}

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c \"$batPath\""
$trigger = New-ScheduledTaskTrigger -Daily -At $RunTime
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description "Hohai auto check-in" -Force
Write-Host "Task '$TaskName' created."
Write-Host "Test run: Start-ScheduledTask -TaskName $TaskName"
