#!/usr/bin/env python3
"""
Launch script for full Super Agency runtime mode
Updated for departmental matrix structure - initializes all departmental systems
"""

import logging
import asyncio
import sys, os
import time
from pathlib import Path

# Import departmental systems
from departmental_agent_manager import DepartmentalAgentManager
from agents.orchestrator import main as run_departmental_orchestrator
from matrix_maximizer import MatrixMaximizer
from mobile_command_center_simple import app as mobile_app
from operations_api import app as operations_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting Super Agency runtime - Departmental Matrix Structure v2.0")

    # Initialize departmental agent manager
    root_path = Path(__file__).parent
    agent_manager = DepartmentalAgentManager(root_path)
    logger.info("Departmental Agent Manager initialized")

    # Load organization structure
    if not agent_manager.org_structure:
        logger.error("Failed to load organization structure, aborting")
        return

    logger.info(f"Organization loaded: {agent_manager.org_structure.get('organization', {}).get('name', 'Unknown')}")

    # Run departmental orchestrator (synchronous for now)
    try:
        run_departmental_orchestrator()
        logger.info("Departmental orchestrator completed successfully")
    except Exception as e:
        logger.error(f"Departmental orchestrator failed: {e}")

    # Start matrix maximizer for monitoring
    try:
        matrix = MatrixMaximizer()
        matrix.start_monitoring()
        logger.info("Matrix Maximizer started")
    except Exception as e:
        logger.error(f"Failed to start Matrix Maximizer: {e}")

    # Start mobile command center (background)
    try:
        def start_mobile_center():
            logger.info("Starting Mobile Command Center on port 8081")
            mobile_app.run(host='0.0.0.0', port=8081, debug=False, use_reloader=False)

        import threading
        mobile_thread = threading.Thread(target=start_mobile_center, daemon=True)
        mobile_thread.start()
        logger.info("Mobile Command Center started in background")
    except Exception as e:
        logger.error(f"Failed to start Mobile Command Center: {e}")

    # Start operations API (background)
    try:
        def start_operations_api():
            logger.info("Starting Operations API on port 5001")
            operations_app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)

        operations_thread = threading.Thread(target=start_operations_api, daemon=True)
        operations_thread.start()
        logger.info("Operations API started in background")
    except Exception as e:
        logger.error(f"Failed to start Operations API: {e}")

    # Keep main thread alive
    logger.info("Super Agency departmental systems operational")
    logger.info("Press Ctrl+C to shutdown")

    try:
        while True:
            time.sleep(60)  # Keep alive with periodic checks
            # Could add health checks here
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    except Exception as e:
        logger.error(f"Unexpected error in main loop: {e}")
    finally:
        logger.info("Super Agency shutdown complete")


if __name__ == '__main__':
    main()
