#!/usr/bin/env python3
"""
Tests for tools/system_health_check.py — NCLHealthChecker methods.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from system_health_check import NCLHealthChecker  # noqa: E402


class TestNCLHealthCheckerInit(unittest.TestCase):

    def test_default_config_when_file_missing(self):
        checker = NCLHealthChecker(config_path="/tmp/nonexistent_config.json")  # noqa: S108
        self.assertIn("network", checker.config)
        self.assertIn("paths", checker.config)

    def test_loads_config_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "network": {"relay_port": 9999, "onedrop_port": 1111},
                "paths": {"root": "/tmp/test_ncl"},  # noqa: S108
            }, f)
            f.flush()
            checker = NCLHealthChecker(config_path=f.name)
            self.assertEqual(checker.config["network"]["relay_port"], 9999)
        os.unlink(f.name)


class TestCheckPythonDependencies(unittest.TestCase):

    def test_detects_installed_packages(self):
        checker = NCLHealthChecker(config_path="/dev/null")
        checker.check_python_dependencies()
        result = checker.results["python_deps"]
        # pytest and json are available in test env
        self.assertIn("status", result)

    def test_missing_packages_reported(self):
        checker = NCLHealthChecker(config_path="/dev/null")
        with patch("builtins.__import__", side_effect=ImportError("mock")):
            checker.check_python_dependencies()
        result = checker.results["python_deps"]
        self.assertEqual(result["status"], "FAIL")
        self.assertGreater(len(result["missing"]), 0)


class TestCheckDirectoryStructure(unittest.TestCase):

    def test_missing_dirs_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig_dir = os.getcwd()
            try:
                os.chdir(tmpdir)
                checker = NCLHealthChecker(config_path="/dev/null")
                checker.config["paths"] = {"root": tmpdir}
                checker.check_directory_structure()
                result = checker.results["directory_structure"]
                self.assertIn("status", result)
                # tmpdir has no subdirs, so some will be missing
                self.assertGreater(len(result["missing"]), 0)
            finally:
                os.chdir(orig_dir)

    def test_all_dirs_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create all required dirs
            required_dirs = [
                "data/event_log", "data/quarantine", "data/derived",
                "ncl_agency_runtime/agents", "ncl_agency_runtime/missions",
                "policies", "dist", "audit",
                "workspaces", "_config",
            ]
            for d in required_dirs:
                (Path(tmpdir) / d).mkdir(parents=True, exist_ok=True)

            orig_dir = os.getcwd()
            try:
                os.chdir(tmpdir)
                checker = NCLHealthChecker(config_path="/dev/null")
                checker.config["paths"] = {"root": tmpdir}
                result = checker.check_directory_structure()
                self.assertTrue(result)
            finally:
                os.chdir(orig_dir)


class TestCheckSchemas(unittest.TestCase):

    def test_missing_schema_index(self):
        checker = NCLHealthChecker(config_path="/dev/null")
        with patch("os.path.exists", return_value=False):
            result = checker.check_schemas()
        self.assertFalse(result)

    def test_valid_schema_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            schema_dir = Path(tmpdir) / "schemas" / "ncl.iphone.v1"
            schema_dir.mkdir(parents=True)
            index = {"schemas": {"a": {}, "b": {}}}
            (schema_dir / "index.json").write_text(json.dumps(index))

            checker = NCLHealthChecker(config_path="/dev/null")
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                result = checker.check_schemas()
                self.assertTrue(result)
                self.assertEqual(checker.results["schemas"]["count"], 2)
            finally:
                os.chdir(old_cwd)


class TestCheckGoldenTasks(unittest.TestCase):

    def test_missing_dir(self):
        checker = NCLHealthChecker(config_path="/dev/null")
        with patch("os.path.exists", return_value=False):
            result = checker.check_golden_tasks()
        self.assertFalse(result)

    def test_valid_golden_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "evaluation" / "golden_tasks"
            task_dir.mkdir(parents=True)
            for i in range(1, 4):
                (task_dir / f"golden_{i:04d}.json").write_text("{}")

            checker = NCLHealthChecker(config_path="/dev/null")
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                result = checker.check_golden_tasks()
                self.assertTrue(result)
                self.assertEqual(checker.results["golden_tasks"]["count"], 3)
            finally:
                os.chdir(old_cwd)

    def test_empty_golden_tasks_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            task_dir = Path(tmpdir) / "evaluation" / "golden_tasks"
            task_dir.mkdir(parents=True)

            checker = NCLHealthChecker(config_path="/dev/null")
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                result = checker.check_golden_tasks()
                self.assertFalse(result)
            finally:
                os.chdir(old_cwd)


class TestCheckApiEndpoints(unittest.TestCase):

    @patch("system_health_check.requests.get")
    def test_endpoints_down(self, mock_get):
        mock_get.side_effect = Exception("Connection refused")
        checker = NCLHealthChecker(config_path="/dev/null")
        result = checker.check_api_endpoints()
        self.assertFalse(result)


class TestGenerateReport(unittest.TestCase):

    def test_report_is_markdown(self):
        checker = NCLHealthChecker(config_path="/dev/null")
        checker.results = {"test_comp": {"status": "PASS", "count": 5}}
        report = checker.generate_report()
        self.assertIn("# NCL System Health Report", report)
        self.assertIn("Test Comp", report)


if __name__ == "__main__":
    unittest.main()
