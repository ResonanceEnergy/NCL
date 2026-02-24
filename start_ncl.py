#!/usr/bin/env python3
"""
NCL Startup Script
Starts the Neural Control Language system
"""

import asyncio
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, r"C:\Users\gripa\OneDrive - Grip and Ripp\SuperAgency-Shared\repos\NCL\src")

async def main():
    try:
        from ncl.core.ncc import NCC

        print("🧠 Starting Neural Control Language (NCL) System...")
        ncc = NCC()

        # Initialize
        print("🔄 Initializing system...")
        success = await ncc.initialize()
        if not success:
            print("❌ Initialization failed")
            return 1

        print("✅ System initialized successfully")
        print("🔄 Starting continuous operation...")

        # Keep running
        while True:
            try:
                results = await ncc.orchestrate_cycle()
                print(f"✅ Cycle completed: {len(results)} insights processed")

                # Brief pause between cycles
                await asyncio.sleep(300)  # 5 minutes

            except KeyboardInterrupt:
                print("\n🛑 Shutdown requested by user")
                break
            except Exception as e:
                print(f"❌ Cycle error: {e}")
                await asyncio.sleep(60)  # Wait before retry

        # Shutdown
        print("🔄 Shutting down...")
        await ncc.emergency_shutdown()
        print("✅ Shutdown complete")

        return 0

    except Exception as e:
        print(f"❌ Startup failed: {e}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
