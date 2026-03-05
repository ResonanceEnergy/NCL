import json
import os
import tempfile
from pathlib import Path
import pytest
from ncl_gbx_one_drop.build import DIST


def test_build_generates_files():
    # Run build (it will create dist/ if not exists)
    import subprocess
    result = subprocess.run(['python', 'ncl_gbx_one_drop/build.py'], capture_output=True, text=True)
    assert result.returncode == 0
    
    # Check files exist
    assert os.path.exists(DIST / 'ncl_dox_gbx_001.md')
    assert os.path.exists(DIST / 'insights_150.json')
    assert os.path.exists(DIST / 'insights_150.csv')


def test_insights_json_content():
    # Load generated JSON
    with open(DIST / 'insights_150.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    assert isinstance(data, list)
    assert len(data) == 150
    assert 'id' in data[0]
    assert 'tag' in data[0]
    assert 'title' in data[0]
    assert 'description' in data[0]


def test_markdown_content():
    with open(DIST / 'ncl_dox_gbx_001.md', 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert 'NCL Doctrine — iPhone Glass Brick Exploitation (GBX)' in content
    assert '1. ' in content  # First insight
    assert '150.' in content  # Last insight


def test_csv_content():
    import csv
    with open(DIST / 'insights_150.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    assert len(rows) == 150
    assert 'id' in rows[0]
    assert 'tag' in rows[0]
    assert 'title' in rows[0]
    assert 'description' in rows[0]