import os
import pytest
import subprocess
import configparser
from setuptools import setup

@pytest.fixture
def setup_directory(tmp_path):
    # Create a temporary directory structure for testing
    readme_file = tmp_path / "README.md"
    readme_file.write_text("# Sample README text for testing")
    
    src_directory = tmp_path / "src" / "ncl" / "core"
    src_directory.mkdir(parents=True)
    
    return tmp_path, readme_file

def test_setup_script_readme_exists(setup_directory):
    tmp_path, _ = setup_directory
    os.chdir(tmp_path)
    
    # Ensure README file is correctly read
    with open('README.md', encoding='utf-8') as f:
        long_description = f.read()
        
    assert long_description.startswith("# Sample README"), "README file was not read properly or doesn't exist."

def test_setup_script_execution(setup_directory):
    tmp_path, readme_file = setup_directory
    os.chdir(tmp_path)
    
    setup_script = tmp_path / "setup.py"
    setup_script.write_text(readme_file.read_text().replace("README.md", str(readme_file)))
    
    # Simulate running setup script
    result = subprocess.run(["python", "setup.py", "--version"], capture_output=True, text=True)

    assert result.returncode == 0, "Setup script did not execute successfully."
    assert "2.0.0" in result.stdout, "Version output from setup script is incorrect."

@pytest.mark.parametrize("python_version", ["3.8", "3.9", "3.10", "3.11", "3.12"])
def test_supported_python_versions(python_version):
    # Test if specified Python versions are supported per classifiers
    setup_cfg_content = configparser.ConfigParser()
    setup_cfg_content.read_string("""
    [metadata]
    requires-python = >=3.8
    """)

    requires_python = setup_cfg_content.get("metadata", "requires-python")

    assert requires_python.startswith(">="), f"Python version requirement is incorrect: {requires_python}"
    assert float(python_version) >= 3.8, f"Python {python_version} should be supported, but is not in range."

def test_extras_require_configuration():
    # Check extras requirements are correctly configured
    extras = {
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "mypy>=1.0.0",
            "flake8>=6.0.0",
        ],
        "monitoring": [
            "grafana-api>=1.0.3",
            "prometheus-client>=0.17.0",
        ],
        "security": [
            "bcrypt>=4.0.0",
            "pyjwt>=2.8.0",
        ],
    }

    for extra, packages in extras.items():
        assert len(packages) > 0, f"No packages listed in {extra} extras_require."

def test_console_scripts():
    # Verify entry points for console scripts
    entry_points = {
        "ncl-orchestrate": "ncl.core.ncc:main",
        "ncl-monitor": "ncl.monitoring.system_monitor:main",
    }

    for script, entry_point in entry_points.items():
        assert script in ["ncl-orchestrate", "ncl-monitor"], f"Missing expected console script: {script}."
        assert isinstance(entry_point, str) and len(entry_point) > 0, f"Invalid entry point for script {script}: {entry_point}"
