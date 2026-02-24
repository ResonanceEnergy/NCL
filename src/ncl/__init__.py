# src/ncl/__init__.py
"""
Neural Control Language (NCL)
Master Doctrine v2.0 Implementation

This package implements the cyber-physical organism described in the
NCC Master Doctrine v2.0, providing autonomous system orchestration
and evolution capabilities.
"""

__version__ = "2.0.0"
__author__ = "NCC Development Team"
__description__ = "Neural Control Language - Cyber-physical organism implementation"

from .core import NCC, DigitalTwin, DecisionEngine, MemorySystem

__all__ = ['NCC', 'DigitalTwin', 'DecisionEngine', 'MemorySystem']
