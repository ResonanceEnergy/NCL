#!/usr/bin/env python3
"""
AAC - Run Script
Initialize and run the Automated Accounting Center
"""

import os
import sys
from pathlib import Path

def main():
    """Main AAC run function"""
    print("🚀 AAC - Automated Accounting Center")
    print("=" * 50)
    print("Super Agency Financial Management System")
    print()

    # Check if we're in the right directory
    if not Path("aac_engine.py").exists():
        print("❌ Error: Please run this script from the AAC repository root directory")
        sys.exit(1)

    # Test the accounting engine
    print("🧪 Testing accounting engine...")
    try:
        from aac_engine import AccountingEngine
        engine = AccountingEngine()
        engine.setup_default_accounts()
        print("✅ Accounting engine initialized successfully")
        engine.close()
    except Exception as e:
        print(f"❌ Accounting engine test failed: {e}")
        sys.exit(1)

    # Check if we should run the web dashboard
    if len(sys.argv) > 1 and sys.argv[1] == "--web":
        print("🌐 Starting web dashboard...")
        try:
            from aac_dashboard import app
            print("📊 AAC Dashboard available at: http://localhost:5000")
            app.run(debug=True, host='0.0.0.0', port=5000)
        except Exception as e:
            print(f"❌ Web dashboard failed to start: {e}")
            sys.exit(1)
    else:
        print("💡 Use '--web' flag to start the web dashboard")
        print("📊 Example: python run_aac.py --web")

    print("🎉 AAC system ready!")

if __name__ == "__main__":
    main()