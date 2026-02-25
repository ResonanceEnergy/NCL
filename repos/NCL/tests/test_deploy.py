import pytest
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
from deploy import NCLDeployer, logger

@pytest.fixture
def mock_deployer(tmp_path):
    """Fixture to create a mock NCLDeployer instance."""
    return NCLDeployer(target_dir=str(tmp_path))

@patch("subprocess.run")
def test_check_prerequisites_happy_path(mock_run, mock_deployer):
    """Test that prerequisites check runs without error on a happy path."""
    mock_run.return_value = MagicMock(returncode=0)
    
    # Mock Python version eligibility
    with patch.object(sys, 'version_info', (3, 8, 0)):
        mock_deployer.check_prerequisites()
        mock_run.assert_called_with([sys.executable, "-m", "pip", "--version"], capture_output=True, check=True)

def test_check_prerequisites_python_version_error(mock_deployer):
    """Test that `check_prerequisites` raises an error for unsupported Python version."""
    with patch.object(sys, 'version_info', (3, 7, 0)):  # Mocking Python version lower than supported
        with pytest.raises(RuntimeError, match=r"Python 3\.8\+ required"):
            mock_deployer.check_prerequisites()

@patch("subprocess.run")
def test_check_prerequisites_pip_not_available(mock_run, mock_deployer):
    """Test `check_prerequisites` raises an error if pip is not available."""
    mock_run.side_effect = subprocess.CalledProcessError(1, ['pip'])
    
    with pytest.raises(RuntimeError, match=r"pip not available"):
        mock_deployer.check_prerequisites()

def test_create_directories_happy_path(mock_deployer):
    """Test that `create_directories` creates all required directories."""
    mock_deployer.create_directories()
    
    expected_directories = [
        mock_deployer.data_dir,
        mock_deployer.logs_dir,
        mock_deployer.backups_dir,
        mock_deployer.data_dir / "memory",
        mock_deployer.data_dir / "insights",
        mock_deployer.data_dir / "decisions"
    ]
    
    for directory in expected_directories:
        assert directory.exists() and directory.is_dir(), f"Directory {directory} should exist and be a directory"

@patch("subprocess.run")
def test_install_dependencies_happy_path(mock_run, mock_deployer):
    """Test `install_dependencies` installs requirements successfully."""
    mock_run.return_value = MagicMock(returncode=0)
    
    # Create a dummy requirements.txt
    requirements_path = mock_deployer.project_root / "requirements.txt"
    requirements_path.touch()

    mock_deployer.install_dependencies()
    mock_run.assert_called_with([sys.executable, "-m", "pip", "install", "-r", str(requirements_path)], check=True)
    
    # Clean up dummy file
    requirements_path.unlink()

def test_install_dependencies_no_requirements_file(mock_deployer, caplog):
    """Test `install_dependencies` skips installation if requirements.txt is missing."""
    with caplog.at_level(logging.WARNING):
        mock_deployer.install_dependencies()

    assert "requirements.txt not found" in caplog.text, "Expected warning message about missing requirements.txt"

@patch("subprocess.run")
def test_install_dependencies_failure(mock_run, mock_deployer):
    """Test `install_dependencies` raises an error if installation fails."""
    mock_run.side_effect = subprocess.CalledProcessError(1, ['pip'])
    
    # Create a dummy requirements.txt so function doesn't skip
    requirements_path = mock_deployer.project_root / "requirements.txt"
    requirements_path.touch()

    with pytest.raises(RuntimeError, match=r"Failed to install dependencies"):
        mock_deployer.install_dependencies()

    # Clean up dummy file
    requirements_path.unlink()
