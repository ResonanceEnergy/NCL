#!/usr/bin/env python3
"""
Tests for ncl_agency_runtime/agents/launch.py — argument parsing.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ncl_agency_runtime" / "agents"))

from launch import parse_args  # noqa: E402


class TestLaunchParseArgs(unittest.TestCase):

    def test_default_args(self):
        with patch("sys.argv", ["launch"]):
            args = parse_args()
        self.assertFalse(args.discord)
        self.assertFalse(args.telegram)
        self.assertTrue(args.cli)
        self.assertFalse(args.all)
        self.assertIsNone(args.config)
        self.assertFalse(args.no_cli)

    def test_discord_flag(self):
        with patch("sys.argv", ["launch", "--discord"]):
            args = parse_args()
        self.assertTrue(args.discord)

    def test_telegram_flag(self):
        with patch("sys.argv", ["launch", "--telegram"]):
            args = parse_args()
        self.assertTrue(args.telegram)

    def test_all_flag(self):
        with patch("sys.argv", ["launch", "--all"]):
            args = parse_args()
        self.assertTrue(args.all)

    def test_no_cli_flag(self):
        with patch("sys.argv", ["launch", "--no-cli"]):
            args = parse_args()
        self.assertTrue(args.no_cli)

    def test_config_path(self):
        with patch("sys.argv", ["launch", "--config", "/path/to/config.json"]):
            args = parse_args()
        self.assertEqual(args.config, "/path/to/config.json")

    def test_combined_flags(self):
        with patch("sys.argv", ["launch", "--discord", "--telegram", "--no-cli"]):
            args = parse_args()
        self.assertTrue(args.discord)
        self.assertTrue(args.telegram)
        self.assertTrue(args.no_cli)


if __name__ == "__main__":
    unittest.main()
