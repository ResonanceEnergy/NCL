<#
.SYNOPSIS
    NCL Windows Startup - register, remove, or check all three scheduled tasks.

.DESCRIPTION
    Manages three Windows Scheduled Tasks:

      NCL_AutonomousDaemon  - autonomous runtime loop, starts at every logon
      NCL_RelayServer       - inter-pillar relay on port 8787, starts at every logon
      NCL_YouTubeDigest     - daily YouTube pipeline, runs at 03:00

.PARAMETER Mode
    install   - create all tasks (default)
    uninstall - delete all tasks
    status    - show current registration state

.EXAMPLE
    .\setup_windows_startup.ps1
    .\setup_windows_startup.ps1 -Mode status
    .\setup_windows_startup.ps1 -Mode uninstall
#>

param(
    [ValidateSet("install", "uninstall", "status")]
    [string]$Mode = "install"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

# --- paths -------------------------------------------------------------------
$RepoRoot  = (Resolve-Path "$PSScriptRoot\..\..\").Path.TrimEnd('\')
$DaemonBat = "$RepoRoot\ncl_agency_runtime\scripts\ncl_daemon.bat"
$RelayBat  = "$RepoRoot\ncl_agency_runtime\scripts\ncl_relay.bat"
$DigestBat = "$RepoRoot\tools\youtube_digest_daily.bat"

# --- task definitions --------------------------------------------------------
$Tasks = @(
    [PSCustomObject]@{
        Name      = "NCL_AutonomousDaemon"
        Trigger   = "ONLOGON"
        Action    = "`"$DaemonBat`""
        StartTime = ""
    },
    [PSCustomObject]@{
        Name      = "NCL_RelayServer"
        Trigger   = "ONLOGON"
        Action    = "`"$RelayBat`""
        StartTime = ""
    },
    [PSCustomObject]@{
        Name      = "NCL_YouTubeDigest"
        Trigger   = "DAILY"
        Action    = "`"$DigestBat`""
        StartTime = "03:00"
    }
)

# --- helpers -----------------------------------------------------------------
function Write-Header {
    param([string]$Text)
    Write-Host ""
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host "  $('=' * $Text.Length)" -ForegroundColor DarkCyan
}

function Task-Exists {
    param([string]$Name)
    try { $null = schtasks /Query /TN $Name 2>&1; return ($LASTEXITCODE -eq 0) }
    catch { return $false }
}

# --- install -----------------------------------------------------------------
function Install-Tasks {
    Write-Header "NCL Windows Startup - INSTALL"

    foreach ($t in $Tasks) {
        Write-Host ""
        Write-Host "  >> $($t.Name)" -ForegroundColor Yellow

        $batPath = $t.Action -replace '"', ''
        if (-not (Test-Path $batPath)) {
            Write-Host "    [WARN] Launcher not found: $batPath" -ForegroundColor Red
            Write-Host "    Skipping." -ForegroundColor Red
            continue
        }

        $schtasksArgs = @("/Create", "/TN", $t.Name, "/TR", $t.Action, "/SC", $t.Trigger, "/RL", "LIMITED", "/F")
        if ($t.StartTime -ne "") {
            $schtasksArgs += "/ST"
            $schtasksArgs += $t.StartTime
        }

        $result = & schtasks @schtasksArgs 2>&1
        if ($LASTEXITCODE -eq 0) {
            $triggerLabel = $t.Trigger
            if ($t.StartTime -ne "") { $triggerLabel = "$triggerLabel @ $($t.StartTime)" }
            Write-Host "    [OK]  Registered." -ForegroundColor Green
            Write-Host "          Trigger : $triggerLabel" -ForegroundColor DarkGray
            Write-Host "          Command : $($t.Action)" -ForegroundColor DarkGray
        } else {
            Write-Host "    [FAIL] $result" -ForegroundColor Red
            Write-Host "    Tip: re-run as Administrator if you see Access Denied." -ForegroundColor DarkYellow
        }
    }

    Write-Host ""
    Write-Host "  Done. Tasks activate on next login." -ForegroundColor Green
    Write-Host ""
    Write-Host "  To start NOW without logging out:" -ForegroundColor White
    foreach ($t in $Tasks) {
        Write-Host "    schtasks /Run /TN $($t.Name)" -ForegroundColor DarkGray
    }
    Write-Host ""
}

# --- uninstall ---------------------------------------------------------------
function Uninstall-Tasks {
    Write-Header "NCL Windows Startup - UNINSTALL"

    foreach ($t in $Tasks) {
        Write-Host ""
        Write-Host "  >> $($t.Name)" -ForegroundColor Yellow
        if (-not (Task-Exists $t.Name)) {
            Write-Host "    [SKIP] Not registered." -ForegroundColor DarkGray
            continue
        }
        $result = & schtasks /Delete /TN $t.Name /F 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "    [OK]  Removed." -ForegroundColor Green
        } else {
            Write-Host "    [FAIL] $result" -ForegroundColor Red
        }
    }
    Write-Host ""
}

# --- status ------------------------------------------------------------------
function Show-Status {
    Write-Header "NCL Windows Startup - STATUS"
    Write-Host ""

    $rows = @()
    foreach ($t in $Tasks) {
        if (Task-Exists $t.Name) {
            $csv  = schtasks /Query /TN $t.Name /FO CSV /NH 2>$null
            $info = $csv | ConvertFrom-Csv -Header "Name","NextRun","Status"
            $rows += [PSCustomObject]@{
                Task       = $t.Name
                Registered = "YES"
                Status     = if ($info) { $info.Status } else { "Unknown" }
                NextRun    = if ($info) { $info.NextRun } else { "-" }
            }
        } else {
            $rows += [PSCustomObject]@{
                Task       = $t.Name
                Registered = "NO"
                Status     = "-"
                NextRun    = "-"
            }
        }
    }

    $rows | Format-Table -AutoSize
    Write-Host ""
}

# --- dispatch ----------------------------------------------------------------
switch ($Mode) {
    "install"   { Install-Tasks }
    "uninstall" { Uninstall-Tasks }
    "status"    { Show-Status }
}