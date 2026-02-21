# Super Agency Cross-Platform Refresh - Windows PowerShell Script
# Runs every 5 minutes to sync with Quantum Quasar

param(
    [string]$LogFile = "$PSScriptRoot\logs\refresh_scheduler.log"
)

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$logMessage = "[$timestamp] Starting Cross-Platform Refresh on QUANTUM FORGE"

# Ensure log directory exists
$logDir = Split-Path $LogFile -Parent
if (!(Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# Log start
Add-Content -Path $LogFile -Value $logMessage

try {
    # Change to script directory
    Set-Location $PSScriptRoot

    # Run the Python refresh script
    $pythonPath = Join-Path $PSScriptRoot "cross_platform_refresh.py"
    $process = Start-Process -FilePath "python" -ArgumentList $pythonPath -Wait -PassThru -NoNewWindow

    if ($process.ExitCode -eq 0) {
        $successMsg = "[$timestamp] Refresh completed successfully"
        Add-Content -Path $LogFile -Value $successMsg
        Write-Host $successMsg -ForegroundColor Green
    } else {
        $errorMsg = "[$timestamp] Refresh failed with exit code: $($process.ExitCode)"
        Add-Content -Path $LogFile -Value $errorMsg
        Write-Host $errorMsg -ForegroundColor Red
    }
}
catch {
    $errorMsg = "[$timestamp] PowerShell error: $($_.Exception.Message)"
    Add-Content -Path $LogFile -Value $errorMsg
    Write-Host $errorMsg -ForegroundColor Red
}

$completeMsg = "[$timestamp] Cross-Platform Refresh cycle complete"
Add-Content -Path $LogFile -Value $completeMsg
Add-Content -Path $LogFile -Value ""  # Empty line for readability

Write-Host $completeMsg -ForegroundColor Cyan</content>
<parameter name="filePath">/Users/gripandripphdd/Library/CloudStorage/OneDrive-GripandRipp(2)/SuperAgency-Shared/cross_platform_refresh_windows.ps1