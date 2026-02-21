#!/usr/bin/env python3
"""
Launch script for full Super Agency runtime mode
Initializes Inner Council, executive council, and auxiliary systems.
"""

import logging
import asyncio
import sys, os
import time

# no manual sys.path modifications needed now that packages are properly defined
# root directory (current working directory) is already on sys.path

from inner_council.deploy_agents import InnerCouncilDeployment
from agents.executive_council_orchestrator import ExecutiveCouncilOrchestrator
from quantum_computing_integration import QuantumComputingIntegration
from global_intelligence_network import global_network
from decision_optimizer import DecisionOptimizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    logger.info("Starting Super Agency runtime")

    # initialize deployment
    deployment = InnerCouncilDeployment()
    if not deployment.initialize_agents():
        logger.error("Failed to initialize agents, aborting")
        return

    # start agents (with matrix monitor automatically)
    deployment.start_agents()

    # start executive orchestrator
    exec_orch = ExecutiveCouncilOrchestrator()
    exec_orch.start_council()

    # prepare quantum integration asynchronously
    qc_config = {'quantum_qubits': 8, 'quantum_hybrid_mode': True}
    qc = QuantumComputingIntegration(qc_config)
    asyncio.run(qc.initialize_quantum_processors())

    # configure global network if available
    if global_network is not None:
        # use a config from deployment or static settings
        global_network.config = {
            'global_network_enabled': True,
            'monitoring_interval': 5,
            'aggregation_methods': ['consensus', 'weighted_average', 'bayesian_fusion']
        }
        asyncio.run(global_network.establish_global_connections())
        asyncio.run(global_network.implement_intelligence_aggregation())

    # decision optimizer warmup (no data yet)
    optimizer = DecisionOptimizer()

    try:
        # keep running until interrupted
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown requested; stopping systems")
        deployment.stop_agents()
        exec_orch.stop_council()


if __name__ == "__main__":
    main()
