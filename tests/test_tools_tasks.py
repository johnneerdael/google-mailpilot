"""Tests for task-related tools."""

import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock, mock_open

import pytest
from mcp.server.fastmcp import FastMCP, Context

from imap_mcp.imap_client import ImapClient
from imap_mcp.tools import register_tools


class TestTaskTools:
    """Test task-related tools."""

    @pytest.fixture
    def tools(self):
        """Set up tools for testing."""
        # Create a mock MCP server
        mcp = MagicMock(spec=FastMCP)
        imap_client = MagicMock(spec=ImapClient)

        # Make tool decorator store and return the decorated function
        stored_tools = {}

        def mock_tool_decorator():
            def decorator(func):
                stored_tools[func.__name__] = func
                return func

            return decorator

        mcp.tool = mock_tool_decorator

        # Register tools with our mock
        register_tools(mcp, imap_client)

        # Return the tools dictionary
        return stored_tools

    @pytest.fixture
    def mock_context(self):
        """Create a mock MCP context."""
        context = MagicMock(spec=Context)
        return context

    @pytest.mark.asyncio
    async def test_create_task_with_description(self, tools, mock_context, tmp_path):
        """Test creating a task with only a description."""
        # Get the create_task function
        create_task = tools["create_task"]

        # Prepare a temporary file path
        tasks_file = tmp_path / "tasks.md"

        # Test the create_task tool
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = await create_task(description="Test task", ctx=mock_context)

            # Verify the result
            assert "success" in result.lower()
            assert "Test task" in result

            # Verify the task was written to the file
            assert tasks_file.exists()

            # Read the file and check contents
            content = tasks_file.read_text()
            assert "- [ ] Test task" in content
            assert "Priority: medium" in content

    @pytest.mark.asyncio
    async def test_create_task_with_optional_params(
        self, tools, mock_context, tmp_path
    ):
        """Test creating a task with optional parameters."""
        # Get the create_task function
        create_task = tools["create_task"]

        # Prepare a temporary file path
        tasks_file = tmp_path / "tasks.md"

        # Test the create_task tool
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = await create_task(
                description="Test task with params",
                due_date="2025-04-15",
                priority="high",
                ctx=mock_context,
            )

            # Verify the result
            assert "success" in result.lower()
            assert "Test task with params" in result

            # Verify the task was written to the file
            assert tasks_file.exists()

            # Read the file and check contents
            content = tasks_file.read_text()
            assert "- [ ] Test task with params" in content
            assert "Priority: high" in content
            assert "Due: 2025-04-15" in content

    @pytest.mark.asyncio
    async def test_create_task_appends_to_existing_file(
        self, tools, mock_context, tmp_path
    ):
        """Test creating a task appends to existing tasks file."""
        # Get the create_task function
        create_task = tools["create_task"]

        # Prepare a temporary file path
        tasks_file = tmp_path / "tasks.md"

        # Create an initial tasks file
        tasks_file.write_text("- [ ] Existing task\n")

        # Test the create_task tool
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = await create_task(description="New task", ctx=mock_context)

            # Verify the result
            assert "success" in result.lower()

            # Read the file and check contents
            content = tasks_file.read_text()
            assert content.count("- [ ]") == 2
            assert "Existing task" in content
            assert "New task" in content

    @pytest.mark.asyncio
    async def test_create_task_missing_description(self, tools, mock_context):
        """Test creating a task without a description."""
        # Get the create_task function
        create_task = tools["create_task"]

        # Test the create_task tool with missing description
        result = await create_task(
            description="",  # Empty description
            ctx=mock_context,
        )

        # Verify the result contains an error message
        assert "error" in result.lower()
        assert "description is required" in result.lower()

    @pytest.mark.asyncio
    async def test_create_task_invalid_priority(self, tools, mock_context, tmp_path):
        """Test creating a task with invalid priority."""
        # Get the create_task function
        create_task = tools["create_task"]

        # Test the create_task tool with invalid priority
        result = await create_task(
            description="Task with invalid priority",
            priority="urgent",  # Invalid priority
            ctx=mock_context,
        )

        # Verify the result contains an error message
        assert "error" in result.lower()
        assert "priority" in result.lower()

    @pytest.mark.asyncio
    async def test_create_task_invalid_due_date(self, tools, mock_context, tmp_path):
        """Test creating a task with invalid due date."""
        # Get the create_task function
        create_task = tools["create_task"]

        # Test the create_task tool with invalid due date
        result = await create_task(
            description="Task with invalid due date",
            due_date="not a date",
            ctx=mock_context,
        )

        # Verify the result contains an error message
        assert "error" in result.lower()
        assert "due date" in result.lower()

    @pytest.mark.asyncio
    async def test_create_task_logs_details(self, tools, mock_context, tmp_path):
        """Test that task creation is properly logged."""
        # Get the create_task function
        create_task = tools["create_task"]

        # Prepare a temporary file path
        tasks_file = tmp_path / "tasks.md"

        # Test the create_task tool with logging mock
        with (
            patch("os.getcwd", return_value=str(tmp_path)),
            patch("imap_mcp.tools.logger") as mock_logger,
        ):
            result = await create_task(
                description="Test task for logging", ctx=mock_context
            )

            # Verify logging was called
            mock_logger.info.assert_called()
            log_message = mock_logger.info.call_args[0][0]
            assert "Test task for logging" in log_message
