#!/usr/bin/env python3
"""
Tests for tools/setup_wizard.py — directory creation, config validation, banner.
Uses mocks to avoid interactive prompts and file system side-effects.
"""
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

import setup_wizard  # noqa: E402


class TestSetupWizardConstants(unittest.TestCase):

    def test_required_dirs_not_empty(self):
        self.assertGreater(len(setup_wizard.REQUIRED_DIRS), 5)

    def test_required_dirs_contains_event_log(self):
        self.assertIn("data/event_log", setup_wizard.REQUIRED_DIRS)

    def test_required_dirs_contains_audit(self):
        self.assertIn("audit", setup_wizard.REQUIRED_DIRS)

    def test_required_dirs_contains_memory(self):
        self.assertIn("memory", setup_wizard.REQUIRED_DIRS)

    def test_required_python_packages(self):
        self.assertIn("jsonschema", setup_wizard.REQUIRED_PYTHON_PACKAGES)
        self.assertIn("pytest", setup_wizard.REQUIRED_PYTHON_PACKAGES)


class TestStepCreateDirs(unittest.TestCase):

    def test_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(setup_wizard, "NCL_ROOT", Path(tmpdir)):
            setup_wizard.step_create_dirs()
            for d in setup_wizard.REQUIRED_DIRS:
                self.assertTrue((Path(tmpdir) / d).exists(), f"Missing dir: {d}")


class TestStepCheckPython(unittest.TestCase):

    def test_returns_true_on_modern_python(self):
        # Current Python is 3.14 which is >= 3.9
        result = setup_wizard.step_check_python()
        self.assertTrue(result)


class TestStepValidateConfig(unittest.TestCase):

    def test_valid_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "system": {"name": "NCL", "version": "3.0"},
                "paths": {"root": "~/NCL"},
                "network": {"relay_port": 8787, "local_only": True},
                "schemas": {},
                "memory": {},
            }
            config_path = Path(tmpdir) / "ncl_config.json"
            config_path.write_text(json.dumps(config))
            with patch.object(setup_wizard, "REPO_ROOT", Path(tmpdir)):
                result = setup_wizard.step_validate_config()
                self.assertTrue(result)

    def test_missing_config_file(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(setup_wizard, "REPO_ROOT", Path(tmpdir)):
            result = setup_wizard.step_validate_config()
            self.assertFalse(result)

    def test_incomplete_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"system": {"name": "NCL"}}  # missing keys
            config_path = Path(tmpdir) / "ncl_config.json"
            config_path.write_text(json.dumps(config))
            with patch.object(setup_wizard, "REPO_ROOT", Path(tmpdir)):
                result = setup_wizard.step_validate_config()
                self.assertFalse(result)


class TestPromptYn(unittest.TestCase):

    @patch("builtins.input", return_value="")
    def test_default_true(self, _):
        self.assertTrue(setup_wizard.prompt_yn("q?", default=True))

    @patch("builtins.input", return_value="")
    def test_default_false(self, _):
        self.assertFalse(setup_wizard.prompt_yn("q?", default=False))

    @patch("builtins.input", return_value="y")
    def test_yes(self, _):
        self.assertTrue(setup_wizard.prompt_yn("q?"))

    @patch("builtins.input", return_value="n")
    def test_no(self, _):
        self.assertFalse(setup_wizard.prompt_yn("q?"))

    @patch("builtins.input", return_value="yes")
    def test_yes_full(self, _):
        self.assertTrue(setup_wizard.prompt_yn("q?"))


class TestBanner(unittest.TestCase):

    def test_banner_prints(self):
        """Banner should not raise."""
        setup_wizard.banner()


class TestStepValidateImports(unittest.TestCase):

    def test_all_imports_pass(self):
        # lib_ncl and ncl_memory should import fine in test env
        result = setup_wizard.step_validate_imports()
        self.assertTrue(result)

    @patch("builtins.__import__", side_effect=ImportError("fake"))
    def test_import_failures(self, mock_import):
        result = setup_wizard.step_validate_imports()
        self.assertFalse(result)


class TestStepRunTests(unittest.TestCase):

    @patch("setup_wizard.subprocess.run")
    def test_tests_pass(self, mock_run):
        mock_run.return_value = unittest.mock.MagicMock(
            returncode=0,
            stdout="42 passed in 1.2s\n",
        )
        result = setup_wizard.step_run_tests()
        self.assertTrue(result)

    @patch("setup_wizard.subprocess.run")
    def test_tests_fail(self, mock_run):
        mock_run.return_value = unittest.mock.MagicMock(
            returncode=1,
            stdout="FAILED tests/test_x.py\n2 failed\n",
        )
        result = setup_wizard.step_run_tests()
        self.assertFalse(result)


class TestSummary(unittest.TestCase):

    def test_all_pass(self, ):
        results = {"Python check": True, "Config check": True}
        setup_wizard.summary(results)  # Should not raise

    def test_partial_fail(self):
        results = {"Python check": True, "Config check": False}
        setup_wizard.summary(results)  # Should not raise


if __name__ == "__main__":
    unittest.main()
