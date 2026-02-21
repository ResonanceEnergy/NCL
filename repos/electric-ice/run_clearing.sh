#!/bin/bash
# Electric Ice - Patent Clearing Runner
# Usage: ./run_clearing.sh [technology] [company]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Default parameters
TECHNOLOGY="${1:-electric vehicle battery management}"
COMPANY="${2:-Resonance Energy}"

echo "🧊 Electric Ice - Patent Clearing System"
echo "========================================"
echo "Technology: $TECHNOLOGY"
echo "Company: $COMPANY"
echo "Started: $(date)"
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Setting up virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install/update requirements
pip install -r requirements.txt

# Run patent clearing analysis
echo "Running patent clearing analysis..."
python3 patent_clearing_system.py

echo ""
echo "✅ Analysis complete!"
echo "Check the generated JSON file for results."