import os
import json
import tempfile
from pathlib import Path

import pytest

import agents.common as common


def test_categorize_file():
    assert common.categorize_file("README.md") == "docs"
    assert common.categorize_file("src/main.py") == "code"
    assert common.categorize_file("tests/test_example.py") == "tests"
    assert common.categorize_file(".ncl/mandate.yaml") == "ncl"
    assert common.categorize_file("foo.NCL/whatever") == "code"  # not folder


def test_load_mandate_empty(tmp_path):
    # no files present
    assert common.load_mandate(tmp_path) == {}


def test_load_mandate_yaml(tmp_path):
    content = """
key1: value1
key2:
  - itemA
  - itemB
"""
    mpath = tmp_path / ".ncl"
    mpath.mkdir()
    (mpath / "mandate.yaml").write_text(content)
    result = common.load_mandate(tmp_path)
    assert result["key1"] == "value1"
    assert result["key2"] == ["itemA", "itemB"]


def test_require_consent_for():
    # override config to include one
    common.SENSITIVE_ACTIONS = {"foo"}
    assert common.require_consent_for("foo") is True
    assert common.require_consent_for("bar") is False
