# PowerShell launcher for Super Agency
Write-Host "[1/3] Installing Python dependencies..."
python -m pip install -r requirements.txt

if (Test-Path "apps/monitor/matrix_monitor/monitoring/aac_matrix_monitor_enhanced.py") {
    Write-Host "AAC monitor module detected. UI will use enhanced version."
} else {
    Write-Host "No AAC monitor module present; using simple console UI."
}

Write-Host "[2/3] Starting Super Agency in run mode..."
python run_super_agency.py
