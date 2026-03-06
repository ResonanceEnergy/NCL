#!/usr/bin/env python3
"""
Tests for ncl_agency_runtime/runtime/memory_manager.py CLI — argument parsing and commands.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestMemoryManagerCLIEnabled(unittest.TestCase):
    """Test MemoryManagerCLI methods with mocked memory system enabled."""

    def _make_cli_enabled(self):
        from memory_manager import MemoryManagerCLI
        cli = MemoryManagerCLI.__new__(MemoryManagerCLI)
        cli.memory_manager = MagicMock()
        cli.memory_api = MagicMock()
        cli.learning_engine = MagicMock()
        return cli

    def test_stats_enabled(self):
        cli = self._make_cli_enabled()
        cli.memory_api.get_memory_stats.return_value = {
            "working_memory_count": 5,
            "short_term_count": 10,
            "long_term_count": 20,
            "consolidation_queue_size": 3,
        }
        cli.stats()  # Should print stats without error
        cli.memory_api.get_memory_stats.assert_called_once()

    def test_consolidate_enabled(self):
        cli = self._make_cli_enabled()
        cli.memory_manager.consolidate_memories.return_value = 7
        cli.consolidate()
        cli.memory_manager.consolidate_memories.assert_called_once()

    def test_prune_enabled(self):
        cli = self._make_cli_enabled()
        cli.prune()
        cli.memory_manager.prune_memories.assert_called_once()

    def test_analyze_enabled(self):
        cli = self._make_cli_enabled()
        cli.learning_engine.analyze_recent_events.return_value = {
            "total_events": 42,
            "patterns": {"event_types": {"focus": 10}, "categories": {}},
            "insights": ["insight1"],
            "recommendations": ["rec1"],
        }
        cli.analyze(days=14)
        cli.learning_engine.analyze_recent_events.assert_called_once_with(days_back=14)

    def test_maintenance_enabled(self):
        cli = self._make_cli_enabled()
        cli.memory_manager.consolidate_memories.return_value = 3
        cli.learning_engine.analyze_recent_events.return_value = {
            "total_events": 10, "insights": [], "recommendations": [],
        }
        cli.maintenance()
        cli.memory_manager.consolidate_memories.assert_called_once()
        cli.memory_manager.prune_memories.assert_called_once()
        cli.learning_engine.analyze_recent_events.assert_called_once()

    def test_search_enabled(self):
        cli = self._make_cli_enabled()
        mock_mem = MagicMock()
        mock_mem.memory_type = "episodic"
        mock_mem.id = "abcdef1234567890"
        mock_mem.tags = ["tag1"]
        mock_mem.importance = 0.8
        mock_mem.timestamp.strftime.return_value = "2026-03-10 10:00"
        mock_mem.content = "test content"
        with patch("ncl_memory.search_memories", return_value=[mock_mem]):
            cli.search("test query", limit=5)

    def test_learnings_enabled_dict_content(self):
        cli = self._make_cli_enabled()
        mock_mem = MagicMock()
        mock_mem.content = {"concept": "Python", "knowledge": "Great language", "confidence": 0.9}
        mock_mem.timestamp.strftime.return_value = "2026-03-10 10:00"
        with patch("ncl_memory.search_memories", return_value=[mock_mem]):
            cli.learnings(limit=5)

    def test_learnings_enabled_str_content(self):
        cli = self._make_cli_enabled()
        mock_mem = MagicMock()
        mock_mem.content = "simple learning"
        mock_mem.timestamp.strftime.return_value = "2026-03-10 10:00"
        with patch("ncl_memory.search_memories", return_value=[mock_mem]):
            cli.learnings(limit=5)

    def test_export_stub(self):
        cli = self._make_cli_enabled()
        cli.export("output.json")  # Should print stub message, not raise


class TestMemoryManagerMainDispatch(unittest.TestCase):
    """Test main() dispatches correctly to CLI methods."""

    def test_search_command(self):
        with patch("sys.argv", ["memory_manager", "search", "hello"]), \
             patch("memory_manager.MemoryManagerCLI") as MockCLI:
            from memory_manager import main
            main()
            MockCLI.return_value.search.assert_called_once_with("hello", 10)

    def test_learnings_command(self):
        with patch("sys.argv", ["memory_manager", "learnings", "--limit", "20"]), \
             patch("memory_manager.MemoryManagerCLI") as MockCLI:
            from memory_manager import main
            main()
            MockCLI.return_value.learnings.assert_called_once_with(20)

    def test_export_command(self):
        with patch("sys.argv", ["memory_manager", "export", "out.json"]), \
             patch("memory_manager.MemoryManagerCLI") as MockCLI:
            from memory_manager import main
            main()
            MockCLI.return_value.export.assert_called_once_with("out.json")

    def test_analyze_command_with_days(self):
        with patch("sys.argv", ["memory_manager", "analyze", "--days", "30"]), \
             patch("memory_manager.MemoryManagerCLI") as MockCLI:
            from memory_manager import main
            main()
            MockCLI.return_value.analyze.assert_called_once_with(30)


if __name__ == "__main__":
    unittest.main()
