"""Integration tests for MCP CLI with IMAP server integration.

This test verifies the basics of server configuration and proper CLI interaction with the IMAP MCP server.
Following the project's integration testing framework, all tests
are tagged with @pytest.mark.integration and can be run or skipped with
the --skip-integration flag.
"""

import json
import os
import pytest
import subprocess
import time
import logging
import tempfile
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration

# Define paths and variables
PROJECT_ROOT = Path.cwd()
WRAPPER_SCRIPT = PROJECT_ROOT / "scripts" / "run_imap_mcp_server.sh"


class TestImapMcpServerConfig:
    """Test the IMAP MCP server configuration and basic CLI functionality."""

    def test_wrapper_script_exists(self):
        """Test that the IMAP MCP server wrapper script exists and is executable."""
        assert WRAPPER_SCRIPT.exists(), f"Server script not found: {WRAPPER_SCRIPT}"
        assert os.access(WRAPPER_SCRIPT, os.X_OK), (
            f"Server script not executable: {WRAPPER_SCRIPT}"
        )

        # Verify the script has expected content
        with open(WRAPPER_SCRIPT, "r") as f:
            script_content = f.read()

        # Check for key indicators this is the correct script
        expected_indicators = ["Starting IMAP MCP Server", "PYTHONPATH"]
        for indicator in expected_indicators:
            assert indicator in script_content, (
                f"Expected content '{indicator}' not found in script"
            )

    def test_wrapper_script_help(self):
        """Test that the wrapper script responds to --help."""
        # Run the script with --help
        result = subprocess.run(
            [str(WRAPPER_SCRIPT), "--help"], capture_output=True, text=True
        )

        # Verify it exits successfully and contains expected help output
        assert result.returncode == 0, (
            f"Script --help failed with code {result.returncode}"
        )
        assert "usage:" in result.stdout or "usage:" in result.stderr, (
            "Help output not found"
        )
