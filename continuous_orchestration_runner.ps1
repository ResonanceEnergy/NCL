# Super Agency Continuous Orchestration Runner
# Runs orchestration cycles every 30 minutes for optimization testing

param(
    [int]$IntervalMinutes = 30,
    [switch]$TestMode
)

$IntervalSeconds = $IntervalMinutes * 60
$CycleCount = 0

Write-Host "🧠 Super Agency Continuous Orchestration Runner"
Write-Host "Interval: $IntervalMinutes minutes ($IntervalSeconds seconds)"
Write-Host "Starting continuous cycles..."
Write-Host "Press Ctrl+C to stop"
Write-Host ""

while ($true) {
    $CycleCount++
    $StartTime = Get-Date

    Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - Starting Cycle #$CycleCount"

    try {
        # Run the orchestration cycle
        & python -c "import asyncio; from conductor_agent import ConductorAgent; asyncio.run(ConductorAgent().orchestrate_cycle())"

        $EndTime = Get-Date
        $Duration = ($EndTime - $StartTime).TotalSeconds

        Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - Cycle #$CycleCount completed in $([math]::Round($Duration, 2)) seconds"

        # Log to file
        $LogEntry = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),Cycle_$CycleCount,$([math]::Round($Duration, 2))s"
        Add-Content -Path "continuous_orchestration_log.csv" -Value $LogEntry

    } catch {
        Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - ERROR in Cycle #$CycleCount : $($_.Exception.Message)" -ForegroundColor Red
        $LogEntry = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'),Cycle_$CycleCount,ERROR:$($_.Exception.Message)"
        Add-Content -Path "continuous_orchestration_log.csv" -Value $LogEntry
    }

    # Wait for next cycle (unless in test mode)
    if (-not $TestMode) {
        Write-Host "Waiting $IntervalMinutes minutes until next cycle..."
        Start-Sleep -Seconds $IntervalSeconds
    } else {
        # In test mode, just wait a few seconds
        Write-Host "Test mode: waiting 10 seconds..."
        Start-Sleep -Seconds 10
    }
}