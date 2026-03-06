#!/usr/bin/env python3
"""tests/test_golden_tasks.py — Validate golden task JSON files are well-formed."""

import json
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent.parent / "evaluation" / "golden_tasks"


def _load_golden_files():
    """Return list of (path, data) for all golden task files."""
    files = sorted(GOLDEN_DIR.glob("golden_*.json"))
    return [(f, json.loads(f.read_text(encoding="utf-8"))) for f in files]


@pytest.fixture
def golden_files():
    return _load_golden_files()


class TestGoldenTasks:

    def test_golden_dir_exists(self):
        assert GOLDEN_DIR.exists(), f"Golden task directory not found: {GOLDEN_DIR}"

    def test_at_least_one_golden_task(self):
        files = list(GOLDEN_DIR.glob("golden_*.json"))
        assert len(files) >= 1, "No golden task files found"

    def test_all_files_are_valid_json(self):
        for f in sorted(GOLDEN_DIR.glob("golden_*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            assert isinstance(data, dict), f"{f.name}: root must be a JSON object"

    def test_required_keys_present(self, golden_files):
        """Each golden task must have id, name, input, expected."""
        required = {"id", "name", "input", "expected"}
        for path, data in golden_files:
            missing = required - set(data.keys())
            assert not missing, f"{path.name}: missing keys {missing}"

    def test_id_matches_filename(self, golden_files):
        """The 'id' field should match the filename stem."""
        for path, data in golden_files:
            assert data["id"] == path.stem, (
                f"{path.name}: id={data['id']} does not match filename stem={path.stem}"
            )

    def test_input_is_dict(self, golden_files):
        for path, data in golden_files:
            assert isinstance(data["input"], dict), f"{path.name}: 'input' must be a dict"

    def test_expected_is_dict(self, golden_files):
        for path, data in golden_files:
            assert isinstance(data["expected"], dict), f"{path.name}: 'expected' must be a dict"

    def test_ids_are_unique(self, golden_files):
        ids = [data["id"] for _, data in golden_files]
        assert len(ids) == len(set(ids)), f"Duplicate golden task IDs: {ids}"

    def test_no_empty_names(self, golden_files):
        for path, data in golden_files:
            assert data["name"].strip(), f"{path.name}: 'name' must not be empty"
