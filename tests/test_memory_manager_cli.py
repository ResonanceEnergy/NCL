#!/usr/bin/env python3
"""
Tests for ncl_agency_runtime/runtime/memory_manager.py CLI — argument parsing and commands.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ncl_agency_runtime" / "runtime"))


class TestMemoryManagerCLIParsing(unittest.TestCase):
    """Test argparse configuration for CLI subcommands."""

    def test_stats_command(self):
        from memory_manager import main
        # Just verify main doesn't crash when called with "stats" and mocked memory
        with patch("memory_manager.MEMORY_ENABLED", False), \
             patch("sys.argv", ["memory_manager", "stats"]):
            main()  # Should print "Memory system not available" and return

    def test_consolidate_command(self):
        with patch("memory_manager.MEMORY_ENABLED", False), \
             patch("sys.argv", ["memory_manager", "consolidate"]):
            from memory_manager import main
            main()

    def test_prune_command(self):
        with patch("memory_manager.MEMORY_ENABLED", False), \
             patch("sys.argv", ["memory_manager", "prune"]):
            from memory_manager import main
            main()

    def test_maintenance_command(self):
        with patch("memory_manager.MEMORY_ENABLED", False), \
             patch("sys.argv", ["memory_manager", "maintenance"]):
            from memory_manager import main
            main()

    def test_no_command_prints_help(self):
        with patch("memory_manager.MEMORY_ENABLED", False), \
             patch("sys.argv", ["memory_manager"]):
            from memory_manager import main
            main()  # Should print help and return without error


class TestMemoryManagerCLIClass(unittest.TestCase):
    """Test MemoryManagerCLI methods with mocked dependencies."""

    def _make_cli(self):
        with patch("memory_manager.MEMORY_ENABLED", False):
            from memory_manager import MemoryManagerCLI
            cli = MemoryManagerCLI()
            return cli

    def test_stats_disabled(self):
        cli = self._make_cli()
        cli.stats()  # Should not raise

    def test_consolidate_disabled(self):
        cli = self._make_cli()
        cli.consolidate()

    def test_prune_disabled(self):
        cli = self._make_cli()
        cli.prune()

    def test_analyze_disabled(self):
        cli = self._make_cli()
        cli.analyze(days=7)

    def test_maintenance_disabled(self):
        cli = self._make_cli()
        cli.maintenance()


if __name__ == "__main__":
    unittest.main()
