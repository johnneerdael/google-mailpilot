"""Tasks routes for web UI."""

import os
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse

from workspace_secretary.web import templates, get_template_context
from workspace_secretary.web.auth import require_auth, Session

router = APIRouter()


def get_tasks_file_path() -> str:
    """Get the path to tasks.md file."""
    return os.path.join(os.getcwd(), "tasks.md")


def parse_tasks(content: str) -> list[dict]:
    """Parse tasks.md content into structured task list.

    Format: - [ ] Description (Priority: high, Due: 2026-01-15)
            - [x] Completed task (Priority: medium)
    """
    tasks = []
    lines = content.strip().split("\n") if content.strip() else []

    task_pattern = re.compile(
        r"^- \[([ x])\] (.+?)(?:\s*\((?:Priority:\s*(\w+))?(?:,?\s*Due:\s*(\d{4}-\d{2}-\d{2}))?\))?$"
    )

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        match = task_pattern.match(line)
        if match:
            completed = match.group(1) == "x"
            description = match.group(2).strip()
            priority = match.group(3) or "medium"
            due_date = match.group(4)

            description = re.sub(r"\s*\(Priority:.*$", "", description)

            tasks.append(
                {
                    "id": i,
                    "description": description,
                    "completed": completed,
                    "priority": priority.lower(),
                    "due_date": due_date,
                    "line_number": i,
                }
            )

    return tasks


def serialize_tasks(tasks: list[dict]) -> str:
    """Serialize tasks back to tasks.md format."""
    lines = []
    for task in tasks:
        checkbox = "[x]" if task["completed"] else "[ ]"
        line = f"- {checkbox} {task['description']}"

        meta_parts = []
        if task.get("priority"):
            meta_parts.append(f"Priority: {task['priority']}")
        if task.get("due_date"):
            meta_parts.append(f"Due: {task['due_date']}")

        if meta_parts:
            line += f" ({', '.join(meta_parts)})"

        lines.append(line)

    return "\n".join(lines) + "\n" if lines else ""


@router.get("/tasks", response_class=HTMLResponse)
async def tasks_page(
    request: Request,
    show_completed: bool = Query(False),
    session: Session = Depends(require_auth),
):
    """Full tasks page."""
    tasks_file = get_tasks_file_path()
    tasks = []

    if os.path.exists(tasks_file):
        with open(tasks_file, "r") as f:
            tasks = parse_tasks(f.read())

    if not show_completed:
        tasks = [t for t in tasks if not t["completed"]]

    PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(
        key=lambda t: (
            t["completed"],
            PRIORITY_ORDER.get(t["priority"], 1),
            t["due_date"] or "9999-99-99",
        )
    )

    return templates.TemplateResponse(
        "tasks.html",
        get_template_context(
            request,
            tasks=tasks,
            show_completed=show_completed,
            total_tasks=len(tasks),
            completed_count=sum(1 for t in tasks if t["completed"]),
        ),
    )


@router.get("/api/tasks", response_class=JSONResponse)
async def get_tasks(
    show_completed: bool = Query(False),
    session: Session = Depends(require_auth),
):
    """Get tasks as JSON."""
    tasks_file = get_tasks_file_path()
    tasks = []

    if os.path.exists(tasks_file):
        with open(tasks_file, "r") as f:
            tasks = parse_tasks(f.read())

    if not show_completed:
        tasks = [t for t in tasks if not t["completed"]]

    PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(
        key=lambda t: (
            t["completed"],
            PRIORITY_ORDER.get(t["priority"], 1),
            t["due_date"] or "9999-99-99",
        )
    )

    return {"tasks": tasks, "total": len(tasks)}


@router.get("/api/tasks/sidebar", response_class=HTMLResponse)
async def tasks_sidebar(
    request: Request,
    session: Session = Depends(require_auth),
):
    """Get tasks sidebar partial for inbox view."""
    tasks_file = get_tasks_file_path()
    tasks = []

    if os.path.exists(tasks_file):
        with open(tasks_file, "r") as f:
            tasks = parse_tasks(f.read())

    incomplete_tasks = [t for t in tasks if not t["completed"]]

    PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
    incomplete_tasks.sort(
        key=lambda t: (
            PRIORITY_ORDER.get(t["priority"], 1),
            t["due_date"] or "9999-99-99",
        )
    )

    SIDEBAR_LIMIT = 10
    return templates.TemplateResponse(
        "partials/tasks_sidebar.html",
        get_template_context(
            request,
            tasks=incomplete_tasks[:SIDEBAR_LIMIT],
            total_tasks=len(incomplete_tasks),
            has_more=len(incomplete_tasks) > SIDEBAR_LIMIT,
        ),
    )


@router.post("/api/tasks", response_class=JSONResponse)
async def create_task(
    description: str = Form(...),
    priority: str = Form("medium"),
    due_date: Optional[str] = Form(None),
    session: Session = Depends(require_auth),
):
    """Create a new task."""
    if not description.strip():
        return JSONResponse(
            {"success": False, "error": "Description is required"},
            status_code=400,
        )

    if priority not in ["low", "medium", "high"]:
        return JSONResponse(
            {"success": False, "error": "Invalid priority"},
            status_code=400,
        )

    if due_date:
        try:
            datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            return JSONResponse(
                {"success": False, "error": "Invalid date format"},
                status_code=400,
            )

    tasks_file = get_tasks_file_path()

    task_entry = f"- [ ] {description.strip()} (Priority: {priority}"
    if due_date:
        task_entry += f", Due: {due_date}"
    task_entry += ")\n"

    with open(tasks_file, "a") as f:
        f.write(task_entry)

    return {"success": True, "message": "Task created"}


@router.post("/api/tasks/{task_id}/toggle", response_class=JSONResponse)
async def toggle_task(
    task_id: int,
    session: Session = Depends(require_auth),
):
    """Toggle task completion status."""
    tasks_file = get_tasks_file_path()

    if not os.path.exists(tasks_file):
        return JSONResponse(
            {"success": False, "error": "No tasks file"},
            status_code=404,
        )

    with open(tasks_file, "r") as f:
        tasks = parse_tasks(f.read())

    if task_id < 0 or task_id >= len(tasks):
        return JSONResponse(
            {"success": False, "error": "Task not found"},
            status_code=404,
        )

    tasks[task_id]["completed"] = not tasks[task_id]["completed"]

    with open(tasks_file, "w") as f:
        f.write(serialize_tasks(tasks))

    return {
        "success": True,
        "completed": tasks[task_id]["completed"],
    }


@router.delete("/api/tasks/{task_id}", response_class=JSONResponse)
async def delete_task(
    task_id: int,
    session: Session = Depends(require_auth),
):
    """Delete a task."""
    tasks_file = get_tasks_file_path()

    if not os.path.exists(tasks_file):
        return JSONResponse(
            {"success": False, "error": "No tasks file"},
            status_code=404,
        )

    with open(tasks_file, "r") as f:
        tasks = parse_tasks(f.read())

    if task_id < 0 or task_id >= len(tasks):
        return JSONResponse(
            {"success": False, "error": "Task not found"},
            status_code=404,
        )

    del tasks[task_id]

    with open(tasks_file, "w") as f:
        f.write(serialize_tasks(tasks))

    return {"success": True}
